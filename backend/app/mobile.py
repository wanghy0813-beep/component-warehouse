from datetime import datetime
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from .auth import AuthContext, require_access
from .branding import APP_BRAND_NAME
from .team import (
    team_component_out,
    team_components_out,
    create_component_marker,
    delete_component_marker,
    list_component_markers,
    require_library_member,
    update_component_marker,
    update_component_quantity,
)
from .team_schemas import TeamComponentQuantityUpdate, TeamMarkerCreate, TeamMarkerUpdate
from .database import get_db
from .models import ActivityLog, Component, CompetitionLibraryComponent
from .services.inventory import component_available_quantity, equipment_occupied_quantity, reserved_quantities


router = APIRouter(prefix="/api/mobile/v1", tags=["mobile"])
APP_ROOT = "/hardware"


class ScanResolveRequest(BaseModel):
    value: str = Field(min_length=1, max_length=1000)


class ScanBatchResolveRequest(BaseModel):
    values: list[str] = Field(min_length=1, max_length=50)


@router.get("/capabilities")
def mobile_capabilities():
    return {
        "service": APP_BRAND_NAME,
        "version": "v1",
        "bridge_protocol": "1.0",
        "application_root": APP_ROOT,
        "embed_query": "embed=1",
        "scan": {
            "formats": ["qr_code"],
            "batch_max": 50,
            "supports_multiple_results": True,
            "personal_url": f"{APP_ROOT}/scan/{{componentId}}",
            "team_url": "/component-warehouse/team/scan/{libraryId}/{itemId}",
        },
        "nfc": {
            "supported_payloads": [
                "component_id",
                "lcsc_id",
                "personal_url",
                "team_url",
            ],
        },
        "web_bridge": {
            "global": "window.ComponentWarehouseBridge",
            "methods": [
                "getContext",
                "navigate",
                "openAccountSettings",
                "receiveAuthSession",
                "receiveScan",
                "receiveNfc",
                "requestScan",
                "requestNfc",
                "notify",
            ],
        },
    }


def safe_personal_component(
    db: Session,
    component: Component,
    *,
    include_stock: bool = True,
) -> dict:
    reserved = reserved_quantities(db, [component.id]).get(component.id, 0)
    component_data = {
        "component_id": component.id,
        "id": component.warehouse_code,
        "warehouse_code": component.warehouse_code,
        "name": component.name,
        "model": component.model,
        "normalized_spec": component.normalized_spec,
        "package": component.package,
        "lcsc_number": component.lcsc_number,
        "category": component.category.name if component.category else None,
        "datasheet_url": component.datasheet_url,
    }
    if include_stock:
        component_data.update({
            "quantity": int(component.quantity or 0),
            "occupied_quantity": equipment_occupied_quantity(component),
            "available_quantity": component_available_quantity(component, reserved),
        })
    return {
        "type": "personal_component",
        "component": component_data,
    }


def scan_parts(value: str) -> tuple[str, list[str]]:
    raw = str(value or "").strip()
    if not raw:
        return "identifier", [""]
    parsed = urlparse(raw)
    path = parsed.path if (parsed.scheme or parsed.netloc) else raw
    path = path.split("?", 1)[0].split("#", 1)[0].strip()
    segments = [unquote(item).strip() for item in path.split("/") if unquote(item).strip()]
    if "component-warehouse" in segments:
        root_index = segments.index("component-warehouse")
        segments = segments[root_index + 1:]
    if segments and segments[0] == "hardware":
        segments = segments[1:]
    if len(segments) >= 2 and segments[0] == "scan":
        return "personal", [segments[1]]
    if len(segments) >= 3 and segments[0] == "personal" and segments[1] == "scan":
        return "personal", [segments[2]]
    if len(segments) >= 4 and segments[0] == "team" and segments[1] == "scan":
        return "team", [segments[2], segments[3]]
    if len(segments) >= 2 and segments[-2] == "scan":
        return "identifier", [segments[-1]]
    return "identifier", [unquote(raw.rstrip("/").split("/")[-1].split("?", 1)[0].split("#", 1)[0]).strip()]


@router.post("/resolve")
def resolve_scan(payload: ScanResolveRequest, db: Session = Depends(get_db)):
    kind, parts = scan_parts(payload.value)
    if kind == "team":
        return {
            "type": "team_component",
            "library_id": parts[0],
            "component_id": parts[1],
            "requires_auth": True,
            "url": f"/component-warehouse/team/scan/{parts[0]}/{parts[1]}",
        }
    identifier = parts[0].strip()
    query = db.query(Component).filter(
        Component.revoked_at.is_(None),
        or_(
            Component.warehouse_code == identifier,
            Component.lcsc_number == identifier,
        )
    )
    matches = query.limit(3).all()
    if not matches:
        raise HTTPException(status_code=404, detail={"code": "IDENTIFIER_NOT_FOUND"})
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail={"code": "AMBIGUOUS_IDENTIFIER", "matches": len(matches)},
        )
    return safe_personal_component(db, matches[0], include_stock=False)


@router.get("/personal/components/{component_code}")
def get_personal_component(component_code: str, db: Session = Depends(get_db)):
    matches = (
        db.query(Component)
        .filter(
            Component.revoked_at.is_(None),
            or_(
                Component.warehouse_code == component_code,
                Component.lcsc_number == component_code,
            )
        )
        .limit(3)
        .all()
    )
    if not matches:
        raise HTTPException(status_code=404, detail={"code": "IDENTIFIER_NOT_FOUND"})
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail={"code": "AMBIGUOUS_IDENTIFIER"})
    return safe_personal_component(db, matches[0], include_stock=False)


def batch_result(value: str, matches: list[dict]) -> dict:
    if not matches:
        return {
            "value": value,
            "status": "not_found",
            "error": {"code": "IDENTIFIER_NOT_FOUND"},
        }
    if len(matches) > 1:
        return {
            "value": value,
            "status": "ambiguous",
            "error": {"code": "AMBIGUOUS_IDENTIFIER", "matches": len(matches)},
        }
    return {"value": value, "status": "matched", "component": matches[0]}


@router.post("/personal/resolve-batch")
def resolve_personal_batch(
    payload: ScanBatchResolveRequest,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    results = []
    for raw_value in payload.values:
        value = str(raw_value or "").strip()
        kind, parts = scan_parts(value)
        identifier = parts[0].strip() if kind != "team" else ""
        if not identifier:
            results.append(batch_result(value, []))
            continue
        components = (
            db.query(Component)
            .filter(
                Component.owner_user_id == auth.user_id,
                Component.revoked_at.is_(None),
                or_(
                    Component.warehouse_code == identifier,
                    Component.lcsc_number == identifier,
                ),
            )
            .limit(3)
            .all()
        )
        results.append(
            batch_result(
                value,
                [
                    {
                        **safe_personal_component(db, component)["component"],
                        "type": "personal_component",
                    }
                    for component in components
                ],
            )
        )
    return {
        "results": results,
        "matched": sum(item["status"] == "matched" for item in results),
        "total": len(results),
    }


def candidate_rank(component: Component, query: str) -> tuple[int, str]:
    normalized = query.casefold()
    fields = [
        component.warehouse_code,
        component.lcsc_number,
        component.model,
        component.normalized_spec,
        component.name,
    ]
    values = [str(value or "").casefold() for value in fields]
    if normalized in values[:2]:
        rank = 0
    elif normalized in values:
        rank = 1
    elif any(value.startswith(normalized) for value in values if value):
        rank = 2
    else:
        rank = 3
    return rank, str(component.warehouse_code or "")


@router.get("/personal/candidates")
def personal_scan_candidates(
    q: str = "",
    limit: int = 12,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    query_text = str(q or "").strip()
    if not query_text:
        return []
    like = f"{query_text}%"
    rows = (
        db.query(Component)
        .options(joinedload(Component.category))
        .filter(
            Component.owner_user_id == auth.user_id,
            Component.revoked_at.is_(None),
            or_(
                Component.warehouse_code.ilike(like),
                Component.lcsc_number.ilike(like),
                Component.model.ilike(like),
                Component.normalized_spec.ilike(like),
                Component.name.ilike(like),
            ),
        )
        .limit(min(max(limit * 4, 12), 80))
        .all()
    )
    rows.sort(key=lambda component: candidate_rank(component, query_text))
    return [
        safe_personal_component(db, component)["component"]
        for component in rows[: min(max(limit, 1), 20)]
    ]


@router.post("/team/libraries/{library_id}/resolve-batch")
def resolve_team_batch(
    library_id: str,
    payload: ScanBatchResolveRequest,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    require_library_member(db, library_id, auth)
    items = (
        db.query(CompetitionLibraryComponent)
        .filter(CompetitionLibraryComponent.library_id == library_id)
        .all()
    )
    rendered_values = team_components_out(db, items, auth)
    rendered = list(zip(items, rendered_values))
    results = []
    for raw_value in payload.values:
        value = str(raw_value or "").strip()
        kind, parts = scan_parts(value)
        matches = []
        if kind == "team":
            if parts[0] == library_id:
                matches = [data for item, data in rendered if item.id == parts[1]]
        else:
            identifier = parts[0].strip().casefold()
            matches = [
                data
                for _item, data in rendered
                if identifier
                and identifier in {
                    str(data.get("warehouse_code") or "").casefold(),
                    str(data.get("lcsc_number") or "").casefold(),
                }
            ]
        results.append(batch_result(value, matches[:3]))
    return {
        "results": results,
        "matched": sum(item["status"] == "matched" for item in results),
        "total": len(results),
    }


@router.get("/team/libraries/{library_id}/candidates")
def team_scan_candidates(
    library_id: str,
    q: str = "",
    limit: int = 12,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    require_library_member(db, library_id, auth)
    query_text = str(q or "").strip().casefold()
    if not query_text:
        return []
    rows = (
        db.query(CompetitionLibraryComponent)
        .filter(CompetitionLibraryComponent.library_id == library_id)
        .all()
    )
    rendered = team_components_out(db, rows, auth)
    matches = []
    for item in rendered:
        values = [
            str(item.get(field) or "").casefold()
            for field in [
                "warehouse_code",
                "lcsc_number",
                "model",
                "normalized_spec",
                "name",
            ]
        ]
        if any(value.startswith(query_text) for value in values if value):
            exact = query_text in values
            matches.append((0 if exact else 1, str(item.get("warehouse_code") or ""), item))
    matches.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in matches[: min(max(limit, 1), 20)]]


@router.patch("/personal/components/{component_code}/quantity")
def update_personal_quantity(
    component_code: str,
    payload: TeamComponentQuantityUpdate,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    component = (
        db.query(Component)
        .filter(
            Component.owner_user_id == auth.user_id,
            Component.revoked_at.is_(None),
            Component.warehouse_code == component_code,
        )
        .first()
    )
    if not component:
        raise HTTPException(status_code=404, detail="器件不存在")
    old_quantity = int(component.quantity or 0)
    component.quantity = payload.quantity
    if payload.quantity > old_quantity:
        component.first_stocked_at = component.first_stocked_at or datetime.utcnow()
        component.last_stocked_at = datetime.utcnow()
    elif payload.quantity < old_quantity:
        component.last_outbound_at = datetime.utcnow()
    db.add(
        ActivityLog(
            owner_user_id=auth.user_id,
            action="component.quantity.mobile_update",
            entity_type="component",
            entity_id=component.id,
            component_id=component.id,
            quantity_delta=payload.quantity - old_quantity,
            summary=f"移动端修改 {component.name} 库存数量：{old_quantity} -> {payload.quantity}",
            detail=payload.remark,
        )
    )
    db.commit()
    db.refresh(component)
    return safe_personal_component(db, component)


@router.get("/team/libraries/{library_id}/components/{item_id}")
def get_team_component(
    library_id: str,
    item_id: str,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    require_library_member(db, library_id, auth)
    item = db.get(CompetitionLibraryComponent, item_id)
    if not item or item.library_id != library_id:
        raise HTTPException(status_code=404, detail="器件不存在")
    return team_component_out(db, item, auth)


@router.patch("/team/libraries/{library_id}/components/{item_id}/quantity")
def update_team_quantity(
    library_id: str,
    item_id: str,
    payload: TeamComponentQuantityUpdate,
    request: Request,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    return update_component_quantity(library_id, item_id, payload, request, auth, db)


@router.post("/team/libraries/{library_id}/components/{item_id}/markers")
def add_team_marker(
    library_id: str,
    item_id: str,
    payload: TeamMarkerCreate,
    request: Request,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    return create_component_marker(library_id, item_id, payload, request, auth, db)


@router.get("/team/libraries/{library_id}/components/{item_id}/markers")
def get_team_markers(
    library_id: str,
    item_id: str,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    return list_component_markers(library_id, item_id, auth, db)


@router.put("/team/libraries/{library_id}/components/{item_id}/markers/{marker_id}")
def edit_team_marker(
    library_id: str,
    item_id: str,
    marker_id: str,
    payload: TeamMarkerUpdate,
    request: Request,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    return update_component_marker(
        library_id,
        item_id,
        marker_id,
        payload,
        request,
        auth,
        db,
    )


@router.delete("/team/libraries/{library_id}/components/{item_id}/markers/{marker_id}")
def remove_team_marker(
    library_id: str,
    item_id: str,
    marker_id: str,
    request: Request,
    auth: AuthContext = Depends(require_access),
    db: Session = Depends(get_db),
):
    return delete_component_marker(
        library_id,
        item_id,
        marker_id,
        request,
        auth,
        db,
    )
