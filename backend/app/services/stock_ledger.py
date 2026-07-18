from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from ..models import Component, InventoryLot, StockMovement


MANUAL_LOT_CREATE_MOVEMENT_TYPES = {"manual_lot_create", "team_lot_create"}


def new_uuid() -> str:
    return str(uuid4())


def ensure_component_lot(db: Session, component: Component) -> InventoryLot:
    lot = (
        db.query(InventoryLot)
        .filter(
            InventoryLot.component_id == component.id,
            InventoryLot.status == "active",
        )
        .order_by(InventoryLot.received_at.asc(), InventoryLot.created_at.asc())
        .first()
    )
    if lot:
        return lot
    quantity = max(0, int(component.quantity or 0))
    lot = InventoryLot(
        id=new_uuid(),
        component_id=component.id,
        owner_user_id=component.owner_user_id,
        source_type="legacy",
        source_reference=component.warehouse_code,
        location=component.location,
        initial_quantity=quantity,
        remaining_quantity=quantity,
        status="active",
    )
    db.add(lot)
    db.flush()
    return lot


def migrate_legacy_inventory_lots(db: Session) -> int:
    existing_component_ids = {
        component_id
        for (component_id,) in db.query(InventoryLot.component_id).distinct().all()
    }
    created = 0
    for component in db.query(Component).order_by(Component.id.asc()).all():
        if component.id in existing_component_ids:
            continue
        ensure_component_lot(db, component)
        created += 1
    return created


def record_stock_delta(
    db: Session,
    component: Component,
    delta: int,
    *,
    movement_type: str,
    reason: str | None = None,
    project_id: int | None = None,
    purchase_line_id: str | None = None,
    actor_user_id: int | None = None,
    location: str | None = None,
    unit_cost: float | None = None,
    source_type: str | None = None,
    source_reference: str | None = None,
    lot_id: str | None = None,
) -> list[StockMovement]:
    delta = int(delta)
    if delta == 0:
        return []
    movements: list[StockMovement] = []
    if delta > 0:
        lot = InventoryLot(
            id=new_uuid(),
            component_id=component.id,
            owner_user_id=component.owner_user_id,
            source_type=source_type or ("purchase" if purchase_line_id else movement_type),
            source_reference=source_reference,
            location=location if location is not None else component.location,
            initial_quantity=delta,
            remaining_quantity=delta,
            unit_cost=unit_cost,
            status="active",
            received_at=datetime.utcnow(),
        )
        db.add(lot)
        db.flush()
        movements.append(
            StockMovement(
                id=new_uuid(),
                component_id=component.id,
                lot_id=lot.id,
                owner_user_id=component.owner_user_id,
                movement_type=movement_type,
                quantity_delta=delta,
                reason=reason,
                project_id=project_id,
                purchase_line_id=purchase_line_id,
                created_by_user_id=actor_user_id,
            )
        )
    else:
        remaining = abs(delta)
        if lot_id:
            lots = (
                db.query(InventoryLot)
                .filter(
                    InventoryLot.id == lot_id,
                    InventoryLot.component_id == component.id,
                    InventoryLot.status == "active",
                    InventoryLot.remaining_quantity > 0,
                )
                .all()
            )
            if not lots:
                raise ValueError("指定库存批次不存在或已无剩余库存")
            available = sum(max(0, int(lot.remaining_quantity or 0)) for lot in lots)
            if available < remaining:
                raise ValueError(f"指定库存批次库存不足：需要 {remaining}，剩余 {available}")
        else:
            lots = (
                db.query(InventoryLot)
                .filter(
                    InventoryLot.component_id == component.id,
                    InventoryLot.status == "active",
                    InventoryLot.remaining_quantity > 0,
                )
                .order_by(InventoryLot.received_at.asc(), InventoryLot.created_at.asc())
                .all()
            )
        if not lots:
            lots = [ensure_component_lot(db, component)]
        for lot in lots:
            if remaining <= 0:
                break
            used = min(remaining, max(0, int(lot.remaining_quantity or 0)))
            if used <= 0:
                continue
            lot.remaining_quantity -= used
            remaining -= used
            movements.append(
                StockMovement(
                    id=new_uuid(),
                    component_id=component.id,
                    lot_id=lot.id,
                    owner_user_id=component.owner_user_id,
                    movement_type=movement_type,
                    quantity_delta=-used,
                    reason=reason,
                    project_id=project_id,
                    purchase_line_id=purchase_line_id,
                    created_by_user_id=actor_user_id,
                )
            )
        if remaining > 0:
            movements.append(
                StockMovement(
                    id=new_uuid(),
                    component_id=component.id,
                    lot_id=None,
                    owner_user_id=component.owner_user_id,
                    movement_type=movement_type,
                    quantity_delta=-remaining,
                    reason=f"{reason or ''}\n兼容历史负库存差额".strip(),
                    project_id=project_id,
                    purchase_line_id=purchase_line_id,
                    created_by_user_id=actor_user_id,
                )
            )
    db.add_all(movements)
    return movements


def inventory_lot_delete_eligibility(
    db: Session,
    component: Component,
    lot: InventoryLot,
) -> tuple[bool, str | None]:
    if lot.component_id != component.id:
        return False, "库存批次不属于当前器件"
    if lot.status != "active":
        return False, "库存批次已删除或不可用"
    initial_quantity = max(0, int(lot.initial_quantity or 0))
    remaining_quantity = max(0, int(lot.remaining_quantity or 0))
    if initial_quantity <= 0:
        return False, "空批次不能删除"
    if remaining_quantity != initial_quantity:
        return False, "该批次已经发生扣减，需保留库存流水"
    movements = (
        db.query(StockMovement)
        .filter(StockMovement.lot_id == lot.id)
        .order_by(StockMovement.created_at.asc(), StockMovement.id.asc())
        .all()
    )
    creation_movements = [
        movement
        for movement in movements
        if movement.movement_type in MANUAL_LOT_CREATE_MOVEMENT_TYPES
        and int(movement.quantity_delta or 0) == initial_quantity
    ]
    if len(creation_movements) != 1 or len(movements) != 1:
        return False, "仅支持删除未使用过的手工新增批次"
    if int(component.quantity or 0) < initial_quantity:
        return False, "当前总库存不足，不能自动撤销该批次"
    return True, None


def delete_unused_manual_lot(
    db: Session,
    component: Component,
    lot: InventoryLot,
    *,
    actor_user_id: int | None,
    movement_type: str,
    reason: str,
) -> int:
    can_delete, block_reason = inventory_lot_delete_eligibility(db, component, lot)
    if not can_delete:
        raise ValueError(block_reason or "库存批次不能删除")
    quantity = int(lot.remaining_quantity or 0)
    record_stock_delta(
        db,
        component,
        -quantity,
        movement_type=movement_type,
        reason=reason,
        actor_user_id=actor_user_id,
        lot_id=lot.id,
    )
    component.quantity = max(0, int(component.quantity or 0) - quantity)
    lot.status = "deleted"
    db.flush()
    return quantity


def reconcile_component_lots(db: Session, component: Component) -> int:
    lot_total = (
        db.query(InventoryLot)
        .filter(
            InventoryLot.component_id == component.id,
            InventoryLot.status == "active",
        )
        .with_entities(InventoryLot.remaining_quantity)
        .all()
    )
    current = sum(max(0, int(value or 0)) for (value,) in lot_total)
    target = max(0, int(component.quantity or 0))
    delta = target - current
    if delta:
        record_stock_delta(
            db,
            component,
            delta,
            movement_type="compatibility_reconcile",
            reason="兼容旧库存总量",
            actor_user_id=component.owner_user_id,
        )
    return delta
