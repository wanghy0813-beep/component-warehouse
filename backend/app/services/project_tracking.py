import re
import secrets
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    Component,
    Project,
    ProjectBoard,
    ProjectBomImportBatch,
    ProjectBomImportRow,
    ProjectBomItem,
    ProjectBomSolderPoint,
    ProjectCodeAlias,
    ProjectExpense,
    ProjectFabricationRevision,
    ProjectMaterialCostEvent,
    ProjectPcbVersion,
    PurchaseLine,
    PurchaseOrder,
)


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
PROJECT_CODE_PATTERN = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")

PROJECT_STATUS_LABELS = {
    "planning": "方案规划",
    "component_selection": "零件选型",
    "schematic": "原理图准备",
    "pcb_design": "PCB 设计",
    "fabricating": "打板中",
    "assembly_testing": "装配调试",
    "validated": "验证完成",
    "delivered": "已交付",
    "paused": "暂停",
    "cancelled": "取消",
    # Historical values deliberately remain visible and are not guessed into a stage.
    "active": "进行中（待整理）",
    "completed": "已完成（待整理）",
    "archived": "已归档",
}
PROJECT_ACTIVE_STATUSES = {
    "planning",
    "component_selection",
    "schematic",
    "pcb_design",
    "fabricating",
    "assembly_testing",
    "active",
}
PROJECT_STATUS_ORDER = [
    "planning",
    "component_selection",
    "schematic",
    "pcb_design",
    "fabricating",
    "assembly_testing",
    "validated",
    "delivered",
]

PCB_VERSION_STATUS_LABELS = {
    "designing": "设计中",
    "fabricating": "打板中",
    "assembly_testing": "装配测试",
    "passed": "验证通过",
    "failed": "验证失败",
    "retired": "已停用",
}

EXPENSE_CATEGORY_LABELS = {
    "pcb_fabrication": "PCB 打样",
    "assembly_smt": "贴片/装配",
    "shipping_tax": "运费税费",
    "enclosure_mechanical": "外壳与机械",
    "tooling": "工装",
    "other": "其他",
}


def shanghai_today() -> date:
    return datetime.now(SHANGHAI_TZ).date()


def normalize_project_code(value: str | None) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        raise ValueError("项目编号不能为空")
    if len(normalized) > 80:
        raise ValueError("项目编号不能超过 80 个字符")
    if not PROJECT_CODE_PATTERN.fullmatch(normalized):
        raise ValueError("项目编号只能包含字母、数字和连字符，且不能以连字符开头或结尾")
    return normalized


def normalize_version_code(value: str | None) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        raise ValueError("PCB 版本号不能为空")
    if len(normalized) > 40 or not re.fullmatch(r"V?[A-Z0-9]+(?:[._-][A-Z0-9]+)*", normalized):
        raise ValueError("PCB 版本号只能包含字母、数字、点、下划线和连字符")
    return normalized if normalized.startswith("V") else f"V{normalized}"


def iso_week_label(value: date | None) -> str | None:
    if not value:
        return None
    iso_year, iso_week, _ = value.isocalendar()
    return f"{iso_year}W{iso_week:02d}"


def project_period(project: Project) -> dict:
    start = project.start_date
    end = project.end_date
    effective_end = end or shanghai_today()
    actual_days = max(1, (effective_end - start).days + 1) if start else None
    return {
        "start_date": start,
        "end_date": end,
        "start_week": iso_week_label(start),
        "end_week": iso_week_label(end),
        "actual_days": actual_days,
        "actual_weeks": round(actual_days / 7, 1) if actual_days else None,
    }


def project_by_code_or_alias(db: Session, owner_user_id: int, code: str) -> tuple[Project | None, bool]:
    try:
        normalized = normalize_project_code(code)
    except ValueError:
        return None, False
    project = (
        db.query(Project)
        .filter(
            Project.scope_type == "personal",
            Project.owner_user_id == owner_user_id,
            func.upper(Project.project_code) == normalized,
        )
        .first()
    )
    if project:
        return project, False
    alias = (
        db.query(ProjectCodeAlias)
        .join(Project, Project.id == ProjectCodeAlias.project_id)
        .filter(
            Project.owner_user_id == owner_user_id,
            Project.scope_type == "personal",
            func.upper(ProjectCodeAlias.old_code) == normalized,
        )
        .first()
    )
    return (db.get(Project, alias.project_id), True) if alias else (None, False)


def assert_project_code_available(db: Session, normalized: str, project_id: int | None = None) -> None:
    project_query = db.query(Project.id).filter(func.upper(Project.project_code) == normalized)
    alias_query = db.query(ProjectCodeAlias.project_id).filter(func.upper(ProjectCodeAlias.old_code) == normalized)
    if project_id is not None:
        project_query = project_query.filter(Project.id != project_id)
        alias_query = alias_query.filter(ProjectCodeAlias.project_id != project_id)
    if project_query.first() or alias_query.first():
        raise ValueError("项目编号或其历史别名已存在")


def active_version(db: Session, project: Project, create_if_missing: bool = False) -> ProjectPcbVersion | None:
    version = db.get(ProjectPcbVersion, project.active_pcb_version_id) if project.active_pcb_version_id else None
    if version and version.project_id == project.id:
        return version
    version = (
        db.query(ProjectPcbVersion)
        .filter(ProjectPcbVersion.project_id == project.id, ProjectPcbVersion.archived_at.is_(None))
        .order_by(ProjectPcbVersion.sequence_number.desc())
        .first()
    )
    if version:
        project.active_pcb_version_id = version.id
        return version
    return create_initial_version(db, project) if create_if_missing else None


def create_initial_version(db: Session, project: Project, actor_user_id: int | None = None) -> ProjectPcbVersion:
    version = ProjectPcbVersion(
        project_id=project.id,
        sequence_number=1,
        version_code="V1",
        status="designing",
        created_by_user_id=actor_user_id or project.owner_user_id,
    )
    db.add(version)
    db.flush()
    project.active_pcb_version_id = version.id
    # Compatibility bridge for callers that create a historical personal project directly.
    for model in (ProjectBomItem, ProjectBoard, ProjectBomImportBatch, ProjectBomImportRow, ProjectFabricationRevision):
        db.query(model).filter(
            model.project_id == project.id,
            model.pcb_version_id.is_(None),
        ).update({model.pcb_version_id: version.id}, synchronize_session=False)
    return version


def next_version_sequence(db: Session, project_id: int) -> int:
    return int(
        db.query(func.max(ProjectPcbVersion.sequence_number))
        .filter(ProjectPcbVersion.project_id == project_id)
        .scalar()
        or 0
    ) + 1


def create_version(
    db: Session,
    project: Project,
    actor_user_id: int,
    *,
    version_code: str | None = None,
    status: str = "designing",
    change_summary: str | None = None,
    copy_from_version_id: int | None = None,
) -> ProjectPcbVersion:
    if status not in PCB_VERSION_STATUS_LABELS:
        raise ValueError("不支持的 PCB 版本状态")
    sequence = next_version_sequence(db, project.id)
    if sequence > 1 and not str(change_summary or "").strip():
        raise ValueError("V2 及后续版本必须填写变更说明")
    code = normalize_version_code(version_code or f"V{sequence}")
    if db.query(ProjectPcbVersion.id).filter(
        ProjectPcbVersion.project_id == project.id,
        func.upper(ProjectPcbVersion.version_code) == code,
    ).first():
        raise ValueError("该项目内 PCB 版本号已存在")
    source = None
    if copy_from_version_id:
        source = db.get(ProjectPcbVersion, copy_from_version_id)
        if not source or source.project_id != project.id:
            raise ValueError("复制来源版本不存在")
    elif sequence > 1:
        source = active_version(db, project)
    version = ProjectPcbVersion(
        project_id=project.id,
        sequence_number=sequence,
        version_code=code,
        status=status,
        change_summary=str(change_summary or "").strip() or None,
        created_by_user_id=actor_user_id,
    )
    db.add(version)
    db.flush()
    if source:
        for item in db.query(ProjectBomItem).filter(
            ProjectBomItem.project_id == project.id,
            ProjectBomItem.pcb_version_id == source.id,
        ).all():
            db.add(
                ProjectBomItem(
                    project_id=project.id,
                    pcb_version_id=version.id,
                    component_id=item.component_id,
                    required_quantity=item.required_quantity,
                    status=item.status,
                    remark=item.remark,
                )
            )
    project.active_pcb_version_id = version.id
    project.active_fabrication_revision_id = None
    return version


def version_stats(db: Session, project: Project, version: ProjectPcbVersion) -> dict:
    bom_items = db.query(ProjectBomItem).filter(
        ProjectBomItem.project_id == project.id,
        ProjectBomItem.pcb_version_id == version.id,
    ).all()
    board_count = db.query(ProjectBoard.id).filter(
        ProjectBoard.project_id == project.id,
        ProjectBoard.pcb_version_id == version.id,
    ).count()
    item_ids = [item.id for item in bom_items]
    points = (
        db.query(ProjectBomSolderPoint)
        .filter(ProjectBomSolderPoint.bom_item_id.in_(item_ids))
        .all()
        if item_ids
        else []
    )
    cost = cost_summary(db, project, version_id=version.id, include_versions=False)
    return {
        "id": version.id,
        "project_id": project.id,
        "sequence_number": version.sequence_number,
        "version_code": version.version_code,
        "status": version.status,
        "status_label": PCB_VERSION_STATUS_LABELS.get(version.status, version.status),
        "change_summary": version.change_summary,
        "active": project.active_pcb_version_id == version.id,
        "bom_item_count": len(bom_items),
        "board_count": board_count,
        "solder_total": len(points),
        "soldered_count": sum(1 for point in points if point.soldered),
        "solder_progress": round(sum(1 for point in points if point.soldered) / len(points) * 100) if points else 0,
        "material_estimate": cost["bom_unit_estimate"],
        "actual_material_cost": cost["actual_material_cost"],
        "direct_expense": cost["direct_expense"],
        "comprehensive_cost": cost["comprehensive_cost"],
        "unpriced_count": cost["unpriced_bom_items"] + cost["unpriced_material_events"],
        "validated_at": version.validated_at,
        "archived_at": version.archived_at,
        "created_at": version.created_at,
        "updated_at": version.updated_at,
    }


def _money(value: Decimal | float | int | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.000001"))


def _event_amount(event: ProjectMaterialCostEvent) -> Decimal:
    return _money(event.amount) if event.amount is not None else Decimal("0")


def append_material_cost_event(
    db: Session,
    *,
    project: Project,
    point: ProjectBomSolderPoint,
    component: Component,
    event_type: str,
    quantity_delta: int,
    actor_user_id: int | None,
    source_operation_id: str | None,
    unit_cost: Decimal | None = None,
    price_from_current: bool = True,
    reversal_of_event_id: str | None = None,
    note: str | None = None,
) -> ProjectMaterialCostEvent:
    bom_item = db.get(ProjectBomItem, point.bom_item_id)
    board = db.get(ProjectBoard, point.board_id) if point.board_id else None
    version_id = (board.pcb_version_id if board else None) or (bom_item.pcb_version_id if bom_item else None) or project.active_pcb_version_id
    snapshot = component.average_unit_price if price_from_current else unit_cost
    snapshot = Decimal(str(snapshot)) if snapshot is not None else None
    event = ProjectMaterialCostEvent(
        id=secrets.token_hex(16),
        project_id=project.id,
        pcb_version_id=version_id,
        board_id=point.board_id,
        bom_item_id=point.bom_item_id,
        solder_point_id=point.id,
        component_id=component.id,
        event_type=event_type,
        quantity_delta=quantity_delta,
        unit_cost_snapshot=snapshot,
        amount=(snapshot * quantity_delta if snapshot is not None else None),
        unpriced=snapshot is None,
        source_operation_id=source_operation_id,
        reversal_of_event_id=reversal_of_event_id,
        note=note,
        created_by_user_id=actor_user_id,
        created_at=datetime.utcnow(),
    )
    db.add(event)
    return event


def append_material_release_event(
    db: Session,
    *,
    project: Project,
    point: ProjectBomSolderPoint,
    component: Component,
    event_type: str,
    actor_user_id: int | None,
    source_operation_id: str | None,
    note: str | None = None,
) -> ProjectMaterialCostEvent:
    rows = db.query(ProjectMaterialCostEvent).filter(
        ProjectMaterialCostEvent.project_id == project.id,
        ProjectMaterialCostEvent.solder_point_id == point.id,
        ProjectMaterialCostEvent.quantity_delta != 0,
    ).order_by(ProjectMaterialCostEvent.created_at.asc(), ProjectMaterialCostEvent.id.asc()).all()
    stack: list[ProjectMaterialCostEvent] = []
    for row in rows:
        quantity = int(row.quantity_delta or 0)
        if quantity > 0:
            stack.extend([row] * quantity)
        elif quantity < 0:
            for _ in range(abs(quantity)):
                if stack:
                    stack.pop()
    source = stack[-1] if stack else None
    return append_material_cost_event(
        db,
        project=project,
        point=point,
        component=component,
        event_type=event_type,
        quantity_delta=-1,
        actor_user_id=actor_user_id,
        source_operation_id=source_operation_id,
        unit_cost=source.unit_cost_snapshot if source else None,
        price_from_current=False,
        reversal_of_event_id=source.id if source else None,
        note=note,
    )


def reverse_material_events_for_operation(
    db: Session,
    *,
    project: Project,
    operation_id: str,
    actor_user_id: int,
    reversal_operation_id: str,
) -> int:
    originals = db.query(ProjectMaterialCostEvent).filter(
        ProjectMaterialCostEvent.project_id == project.id,
        ProjectMaterialCostEvent.source_operation_id == operation_id,
    ).all()
    changed = 0
    for original in originals:
        if db.query(ProjectMaterialCostEvent.id).filter(
            ProjectMaterialCostEvent.reversal_of_event_id == original.id,
            ProjectMaterialCostEvent.source_operation_id == reversal_operation_id,
        ).first():
            continue
        reversal = ProjectMaterialCostEvent(
            id=secrets.token_hex(16),
            project_id=original.project_id,
            pcb_version_id=original.pcb_version_id,
            board_id=original.board_id,
            bom_item_id=original.bom_item_id,
            solder_point_id=original.solder_point_id,
            component_id=original.component_id,
            event_type=f"undo_{original.event_type}"[:40],
            quantity_delta=-int(original.quantity_delta),
            unit_cost_snapshot=original.unit_cost_snapshot,
            amount=(-original.amount if original.amount is not None else None),
            unpriced=bool(original.unpriced),
            source_operation_id=reversal_operation_id,
            reversal_of_event_id=original.id,
            note="撤销装配操作的反向成本流水",
            created_by_user_id=actor_user_id,
            created_at=datetime.utcnow(),
        )
        db.add(reversal)
        changed += 1
    return changed


def fill_unpriced_material_events(db: Session, project: Project, actor_user_id: int) -> dict:
    events = db.query(ProjectMaterialCostEvent).filter(
        ProjectMaterialCostEvent.project_id == project.id,
        ProjectMaterialCostEvent.unpriced.is_(True),
        ProjectMaterialCostEvent.unit_cost_snapshot.is_(None),
    ).all()
    filled = 0
    remaining = 0
    for event in events:
        component = db.get(Component, event.component_id)
        if not component or component.average_unit_price is None:
            remaining += 1
            continue
        price = Decimal(str(component.average_unit_price))
        event.unit_cost_snapshot = price
        event.amount = price * int(event.quantity_delta)
        event.unpriced = False
        event.note = "；".join(filter(None, [event.note, f"由用户 {actor_user_id} 显式补齐历史未计价快照"]))
        filled += 1
    return {"filled": filled, "remaining": remaining}


def expense_out(expense: ProjectExpense, version: ProjectPcbVersion | None = None) -> dict:
    return {
        "id": expense.id,
        "project_id": expense.project_id,
        "pcb_version_id": expense.pcb_version_id,
        "version_code": version.version_code if version else None,
        "category": expense.category,
        "category_label": EXPENSE_CATEGORY_LABELS.get(expense.category, expense.category),
        "amount": _money(expense.amount),
        "currency": expense.currency,
        "occurred_on": expense.occurred_on,
        "vendor": expense.vendor,
        "note": expense.note,
        "attachment_asset_id": expense.attachment_asset_id,
        "archived_at": expense.archived_at,
        "created_at": expense.created_at,
        "updated_at": expense.updated_at,
    }


def cost_summary(
    db: Session,
    project: Project,
    *,
    version_id: int | None = None,
    include_versions: bool = True,
) -> dict:
    bom_query = db.query(ProjectBomItem).filter(ProjectBomItem.project_id == project.id)
    board_query = db.query(ProjectBoard).filter(ProjectBoard.project_id == project.id)
    event_query = db.query(ProjectMaterialCostEvent).filter(ProjectMaterialCostEvent.project_id == project.id)
    expense_query = db.query(ProjectExpense).filter(
        ProjectExpense.project_id == project.id,
        ProjectExpense.archived_at.is_(None),
    )
    if version_id is not None:
        bom_query = bom_query.filter(ProjectBomItem.pcb_version_id == version_id)
        board_query = board_query.filter(ProjectBoard.pcb_version_id == version_id)
        event_query = event_query.filter(ProjectMaterialCostEvent.pcb_version_id == version_id)
        expense_query = expense_query.filter(ProjectExpense.pcb_version_id == version_id)
    bom_items = bom_query.all()
    board_count = board_query.count()
    events = event_query.order_by(ProjectMaterialCostEvent.created_at.asc()).all()
    expenses = expense_query.order_by(ProjectExpense.occurred_on.asc()).all()

    bom_estimate = Decimal("0")
    unpriced_bom = 0
    for item in bom_items:
        component = db.get(Component, item.component_id)
        if not component or component.average_unit_price is None:
            unpriced_bom += 1
            continue
        bom_estimate += Decimal(str(component.average_unit_price)) * int(item.required_quantity or 0)
    actual_material = sum((_event_amount(event) for event in events), Decimal("0"))
    direct_expense = sum((_money(expense.amount) for expense in expenses), Decimal("0"))

    unpriced_net: dict[tuple[int | None, int], int] = defaultdict(int)
    component_costs: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    weekly: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"material": Decimal("0"), "expense": Decimal("0")}
    )
    for event in events:
        if event.unpriced:
            unpriced_net[(event.solder_point_id, event.component_id)] += int(event.quantity_delta)
        component_costs[event.component_id] += _event_amount(event)
        event_date = event.created_at.date() if event.created_at else shanghai_today()
        weekly[iso_week_label(event_date)]["material"] += _event_amount(event)
    category_costs: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for expense in expenses:
        amount = _money(expense.amount)
        category_costs[expense.category] += amount
        weekly[iso_week_label(expense.occurred_on)]["expense"] += amount

    planned_purchase = Decimal("0")
    committed_purchase = Decimal("0")
    if version_id is None:
        orders = db.query(PurchaseOrder).filter(PurchaseOrder.project_id == project.id).all()
        for order in orders:
            amount = sum(
                (
                    Decimal(str(line.unit_price or 0)) * int(line.ordered_quantity or 0)
                    for line in db.query(PurchaseLine).filter(PurchaseLine.purchase_order_id == order.id).all()
                ),
                Decimal("0"),
            )
            if order.status in {"planned", "draft"}:
                planned_purchase += amount
            elif order.status not in {"cancelled", "archived"}:
                committed_purchase += amount

    top_items = []
    for component_id, amount in component_costs.items():
        component = db.get(Component, component_id)
        top_items.append(
            {
                "type": "material",
                "key": str(component_id),
                "name": component.name if component else f"器件 {component_id}",
                "amount": _money(amount),
            }
        )
    for category, amount in category_costs.items():
        top_items.append(
            {
                "type": "expense",
                "key": category,
                "name": EXPENSE_CATEGORY_LABELS.get(category, category),
                "amount": _money(amount),
            }
        )
    top_items.sort(key=lambda item: abs(item["amount"]), reverse=True)

    result = {
        "project_id": project.id,
        "project_code": project.project_code,
        "pcb_version_id": version_id,
        "currency": "CNY",
        "bom_unit_estimate": _money(bom_estimate) if bom_items else None,
        "planned_material_estimate": _money(bom_estimate * max(1, board_count)) if bom_items else None,
        "actual_material_cost": _money(actual_material),
        "direct_expense": _money(direct_expense),
        "comprehensive_cost": _money(actual_material + direct_expense),
        "planned_purchase_amount": _money(planned_purchase),
        "committed_purchase_amount": _money(committed_purchase),
        "unpriced_bom_items": unpriced_bom,
        "unpriced_material_events": sum(1 for quantity in unpriced_net.values() if quantity > 0),
        "top_cost_items": top_items[:10],
        "weekly_trend": [
            {
                "week": week,
                "material": _money(values["material"]),
                "expense": _money(values["expense"]),
                "total": _money(values["material"] + values["expense"]),
            }
            for week, values in sorted(weekly.items())
        ],
        "versions": [],
    }
    if include_versions and version_id is None:
        versions = db.query(ProjectPcbVersion).filter(
            ProjectPcbVersion.project_id == project.id,
            ProjectPcbVersion.archived_at.is_(None),
        ).order_by(ProjectPcbVersion.sequence_number.asc()).all()
        result["versions"] = [
            {
                "id": version.id,
                "version_code": version.version_code,
                **{
                    key: value
                    for key, value in cost_summary(db, project, version_id=version.id, include_versions=False).items()
                    if key
                    in {
                        "bom_unit_estimate",
                        "planned_material_estimate",
                        "actual_material_cost",
                        "direct_expense",
                        "comprehensive_cost",
                        "unpriced_bom_items",
                        "unpriced_material_events",
                    }
                },
            }
            for version in versions
        ]
    return result
