from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import AuthContext, require_access
from .database import get_db
from .engineering_schemas import PurchaseLineCreate, PurchaseOrderCreate, PurchaseReceiptCreate
from .models import (
    CompetitionLibraryComponent,
    Component,
    Project,
    ProjectBomItem,
    PurchaseLine,
    PurchaseOrder,
    PurchaseReceipt,
    SupplierPart,
    User,
)
from .services.stock_ledger import record_stock_delta
from .services.inventory import reserved_quantities
from .team import require_library_editor, require_library_member


router = APIRouter(tags=["purchases"])
ORDER_STATUSES = {"planned", "ordered", "partial", "received", "cancelled"}


@dataclass(frozen=True)
class PurchaseScope:
    scope_type: str
    owner_user_id: int | None
    team_library_id: str | None
    auth: AuthContext


def new_uuid() -> str:
    return str(uuid4())


def personal_scope(auth: AuthContext) -> PurchaseScope:
    return PurchaseScope("personal", auth.user_id, None, auth)


def team_scope(db: Session, library_id: str, auth: AuthContext, edit: bool) -> PurchaseScope:
    if edit:
        require_library_editor(db, library_id, auth)
    else:
        require_library_member(db, library_id, auth)
    return PurchaseScope("team", None, library_id, auth)


def scoped(query, model, scope: PurchaseScope):
    query = query.filter(model.scope_type == scope.scope_type)
    if scope.scope_type == "team":
        return query.filter(model.team_library_id == scope.team_library_id)
    return query.filter(model.owner_user_id == scope.owner_user_id)


def require_order(db: Session, scope: PurchaseScope, order_id: str) -> PurchaseOrder:
    order = scoped(db.query(PurchaseOrder), PurchaseOrder, scope).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="采购单不存在")
    return order


def require_line(db: Session, scope: PurchaseScope, line_id: str) -> tuple[PurchaseOrder, PurchaseLine]:
    line = db.get(PurchaseLine, line_id)
    if not line:
        raise HTTPException(status_code=404, detail="采购行不存在")
    return require_order(db, scope, line.purchase_order_id), line


def order_out(db: Session, order: PurchaseOrder) -> dict:
    lines = (
        db.query(PurchaseLine)
        .filter(PurchaseLine.purchase_order_id == order.id)
        .order_by(PurchaseLine.created_at.asc())
        .all()
    )
    return {
        "id": order.id,
        "scope_type": order.scope_type,
        "project_id": order.project_id,
        "order_number": order.order_number,
        "platform": order.platform,
        "status": order.status,
        "currency": order.currency,
        "note": order.note,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "total_price": round(
            sum(float(item.unit_price or 0) * int(item.ordered_quantity or 0) for item in lines),
            4,
        ),
        "lines": [
            {
                "id": item.id,
                "component_id": item.component_id,
                "supplier_part_id": item.supplier_part_id,
                "receiver_user_id": item.receiver_user_id,
                "description": item.description,
                "ordered_quantity": item.ordered_quantity,
                "received_quantity": item.received_quantity,
                "unit_price": item.unit_price,
                "purchase_url": item.purchase_url,
                "status": item.status,
                "note": item.note,
            }
            for item in lines
        ],
    }


def list_orders_impl(db: Session, scope: PurchaseScope) -> list[dict]:
    rows = scoped(db.query(PurchaseOrder), PurchaseOrder, scope).order_by(PurchaseOrder.updated_at.desc()).all()
    return [order_out(db, item) for item in rows]


def create_order_impl(db: Session, scope: PurchaseScope, payload: PurchaseOrderCreate) -> dict:
    if payload.status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="采购状态无效")
    order = PurchaseOrder(
        id=new_uuid(),
        scope_type=scope.scope_type,
        owner_user_id=scope.owner_user_id,
        team_library_id=scope.team_library_id,
        project_id=payload.project_id,
        order_number=(payload.order_number or "").strip() or None,
        platform=(payload.platform or "").strip() or None,
        status=payload.status,
        currency=payload.currency.strip().upper()[:8] or "CNY",
        note=(payload.note or "").strip() or None,
        created_by_user_id=scope.auth.user_id,
    )
    db.add(order)
    db.commit()
    return order_out(db, order)


def require_project_for_scope(db: Session, scope: PurchaseScope, project_id: int) -> Project:
    project = db.get(Project, project_id)
    valid = bool(
        project
        and (
            (scope.scope_type == "personal" and project.owner_user_id == scope.owner_user_id)
            or (
                scope.scope_type == "team"
                and project.scope_type == "team"
                and project.team_library_id == scope.team_library_id
            )
        )
    )
    if not valid:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def generate_project_purchase_impl(db: Session, scope: PurchaseScope, project_id: int, payload: dict) -> dict:
    project = require_project_for_scope(db, scope, project_id)
    items = db.query(ProjectBomItem).filter(ProjectBomItem.project_id == project.id).all()
    component_ids = [item.component_id for item in items]
    reserved = reserved_quantities(db, component_ids)
    order = PurchaseOrder(
        id=new_uuid(),
        scope_type=scope.scope_type,
        owner_user_id=scope.owner_user_id,
        team_library_id=scope.team_library_id,
        project_id=project.id,
        platform=str(payload.get("platform") or "").strip() or None,
        status="planned",
        currency=str(payload.get("currency") or "CNY").strip().upper()[:8] or "CNY",
        note=str(payload.get("note") or f"项目 {project.name} 自动生成的缺料与安全库存采购计划").strip(),
        created_by_user_id=scope.auth.user_id,
    )
    db.add(order)
    line_count = 0
    for item in items:
        component = db.get(Component, item.component_id)
        if not component:
            continue
        remaining_after_reserved = int(component.quantity or 0) - int(reserved.get(component.id, 0))
        suggested = max(0, int(component.safety_quantity or 0) - remaining_after_reserved)
        if suggested <= 0:
            continue
        supplier_query = db.query(SupplierPart).filter(
            SupplierPart.component_id == component.id,
            SupplierPart.status == "active",
        )
        if scope.scope_type == "team":
            supplier_query = supplier_query.filter(
                SupplierPart.scope_type == "team",
                SupplierPart.team_library_id == scope.team_library_id,
            )
        else:
            supplier_query = supplier_query.filter(
                SupplierPart.scope_type == "personal",
                SupplierPart.owner_user_id == scope.owner_user_id,
            )
        supplier = supplier_query.order_by(SupplierPart.is_preferred.desc(), SupplierPart.updated_at.desc()).first()
        db.add(
            PurchaseLine(
                id=new_uuid(),
                purchase_order_id=order.id,
                component_id=component.id,
                supplier_part_id=supplier.id if supplier else None,
                receiver_user_id=component.owner_user_id,
                description=" · ".join(
                    value
                    for value in [component.manufacturer, component.model or component.name, component.package]
                    if value
                )[:300],
                ordered_quantity=suggested,
                received_quantity=0,
                unit_price=supplier.unit_price if supplier else None,
                purchase_url=supplier.purchase_url if supplier else None,
                status="planned",
                note=(
                    f"项目需求 {item.required_quantity}；全部项目预占 {reserved.get(component.id, 0)}；"
                    f"当前库存 {component.quantity or 0}；最低库存 {component.safety_quantity or 0}"
                ),
            )
        )
        line_count += 1
    if not line_count:
        db.rollback()
        raise HTTPException(status_code=409, detail="当前项目没有需要采购或补足最低库存的物料")
    project.status = "purchasing"
    db.commit()
    return order_out(db, order)


@router.get("/api/purchases")
def list_personal_orders(auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return list_orders_impl(db, personal_scope(auth))


@router.post("/api/purchases")
def create_personal_order(payload: PurchaseOrderCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_order_impl(db, personal_scope(auth), payload)


@router.post("/api/purchases/from-project/{project_id}")
def generate_personal_project_purchase(project_id: int, payload: dict, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return generate_project_purchase_impl(db, personal_scope(auth), project_id, payload)


@router.get("/api/team/libraries/{library_id}/purchases")
def list_team_orders(library_id: str, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return list_orders_impl(db, team_scope(db, library_id, auth, False))


@router.post("/api/team/libraries/{library_id}/purchases")
def create_team_order(library_id: str, payload: PurchaseOrderCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return create_order_impl(db, team_scope(db, library_id, auth, True), payload)


@router.post("/api/team/libraries/{library_id}/purchases/from-project/{project_id}")
def generate_team_project_purchase(library_id: str, project_id: int, payload: dict, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return generate_project_purchase_impl(db, team_scope(db, library_id, auth, True), project_id, payload)


def validate_component(db: Session, scope: PurchaseScope, component_id: int | None) -> Component | None:
    if not component_id:
        return None
    component = db.get(Component, component_id)
    if not component:
        raise HTTPException(status_code=404, detail="元器件不存在")
    if scope.scope_type == "personal" and component.owner_user_id != scope.owner_user_id:
        raise HTTPException(status_code=404, detail="元器件不存在")
    if scope.scope_type == "team":
        linked = (
            db.query(CompetitionLibraryComponent)
            .filter(
                CompetitionLibraryComponent.library_id == scope.team_library_id,
                CompetitionLibraryComponent.cw_component_id == component.id,
            )
            .first()
        )
        if not linked:
            raise HTTPException(status_code=400, detail="元器件未加入团队器件库")
    return component


def add_line_impl(db: Session, scope: PurchaseScope, order_id: str, payload: PurchaseLineCreate) -> dict:
    order = require_order(db, scope, order_id)
    component = validate_component(db, scope, payload.component_id)
    supplier_part = (
        scoped(db.query(SupplierPart), SupplierPart, scope)
        .filter(SupplierPart.id == payload.supplier_part_id)
        .first()
        if payload.supplier_part_id
        else None
    )
    if payload.supplier_part_id and not supplier_part:
        raise HTTPException(status_code=404, detail="供应商料号不存在")
    if supplier_part and supplier_part.component_id != payload.component_id:
        raise HTTPException(status_code=400, detail="供应商料号与元器件不一致")
    receiver_user_id = payload.receiver_user_id
    if scope.scope_type == "personal":
        receiver_user_id = scope.owner_user_id
    elif not receiver_user_id and component:
        receiver_user_id = component.owner_user_id
    if receiver_user_id and not db.get(User, receiver_user_id):
        raise HTTPException(status_code=404, detail="收货成员不存在")
    line = PurchaseLine(
        id=new_uuid(),
        purchase_order_id=order.id,
        component_id=payload.component_id,
        supplier_part_id=payload.supplier_part_id,
        receiver_user_id=receiver_user_id,
        description=payload.description.strip(),
        ordered_quantity=payload.ordered_quantity,
        received_quantity=0,
        unit_price=payload.unit_price,
        purchase_url=(payload.purchase_url or "").strip() or None,
        status="planned" if order.status == "planned" else "ordered",
        note=(payload.note or "").strip() or None,
    )
    db.add(line)
    db.commit()
    return order_out(db, order)


@router.post("/api/purchases/{order_id}/lines")
def add_personal_line(order_id: str, payload: PurchaseLineCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return add_line_impl(db, personal_scope(auth), order_id, payload)


@router.post("/api/team/libraries/{library_id}/purchases/{order_id}/lines")
def add_team_line(library_id: str, order_id: str, payload: PurchaseLineCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return add_line_impl(db, team_scope(db, library_id, auth, True), order_id, payload)


def receive_line_impl(db: Session, scope: PurchaseScope, line_id: str, payload: PurchaseReceiptCreate) -> dict:
    order, line = require_line(db, scope, line_id)
    if not line.component_id:
        raise HTTPException(status_code=400, detail="采购行必须先绑定元器件才能入库")
    component = db.get(Component, line.component_id)
    if not component:
        raise HTTPException(status_code=404, detail="元器件不存在")
    receiver = line.receiver_user_id or component.owner_user_id
    if receiver != component.owner_user_id:
        raise HTTPException(status_code=409, detail="收货成员与当前元器件归属不一致，请先绑定该成员的器件")
    remaining = max(0, int(line.ordered_quantity or 0) - int(line.received_quantity or 0))
    if payload.quantity > remaining:
        raise HTTPException(status_code=400, detail=f"本次到货数量超过未到货数量 {remaining}")
    old_quantity = int(component.quantity or 0)
    component.quantity = old_quantity + payload.quantity
    component.first_stocked_at = component.first_stocked_at or datetime.utcnow()
    component.last_stocked_at = datetime.utcnow()
    if payload.location and not component.location:
        component.location = payload.location
    movements = record_stock_delta(
        db,
        component,
        payload.quantity,
        movement_type="purchase_receipt",
        reason=payload.note or f"采购单 {order.order_number or order.id} 到货",
        purchase_line_id=line.id,
        actor_user_id=scope.auth.user_id,
        location=payload.location,
        unit_cost=line.unit_price,
        source_reference=order.order_number or order.id,
    )
    db.flush()
    lot_id = movements[0].lot_id if movements else None
    receipt = PurchaseReceipt(
        id=new_uuid(),
        purchase_line_id=line.id,
        inventory_lot_id=lot_id,
        quantity=payload.quantity,
        location=payload.location,
        received_by_user_id=scope.auth.user_id,
        note=(payload.note or "").strip() or None,
    )
    db.add(receipt)
    line.received_quantity += payload.quantity
    line.status = "received" if line.received_quantity >= line.ordered_quantity else "partial"
    statuses = [
        status
        for (status,) in db.query(PurchaseLine.status)
        .filter(PurchaseLine.purchase_order_id == order.id)
        .all()
    ] + [line.status]
    order.status = "received" if statuses and all(item == "received" for item in statuses) else "partial"
    db.commit()
    return order_out(db, order)


@router.post("/api/purchases/lines/{line_id}/receive")
def receive_personal_line(line_id: str, payload: PurchaseReceiptCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return receive_line_impl(db, personal_scope(auth), line_id, payload)


@router.post("/api/team/libraries/{library_id}/purchases/lines/{line_id}/receive")
def receive_team_line(library_id: str, line_id: str, payload: PurchaseReceiptCreate, auth: AuthContext = Depends(require_access), db: Session = Depends(get_db)):
    return receive_line_impl(db, team_scope(db, library_id, auth, True), line_id, payload)
