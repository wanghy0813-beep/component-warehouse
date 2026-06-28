import json
import hashlib
import re
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import (
    AppMigration,
    Category,
    Component,
    ComponentIdentityRegistry,
    CompetitionLibraryComponent,
)


V060_COMPONENT_IDENTITIES = "v0.6.0-component-identities"
DEFAULT_CATEGORY_PREFIXES = {
    "电阻": "RES",
    "电容": "CAP",
    "电感": "IND",
    "二极管": "DIO",
    "三极管": "BJT",
    "MOS管": "MOS",
    "芯片": "ICS",
    "连接件": "CON",
    "接口": "IF",
    "保护器件": "PRO",
    "电源": "PWR",
    "开关": "SWT",
    "传感器": "SEN",
    "开发板": "DEV",
    "显示模块": "DIS",
    "机电件": "MEC",
    "功能模块": "FNC",
    "通信模块": "COM",
    "散热件": "HET",
    "结构件": "STR",
    "时钟源": "CLK",
    "其他": "OTH",
    "未分类": "UNC",
}

# Three characters are required. IFC is used instead of IF for the interface category.
DEFAULT_CATEGORY_PREFIXES["接口"] = "IFC"
CODE_PATTERN = re.compile(r"^[A-Z0-9]{3}-\d{8}$")
PREFIX_PATTERN = re.compile(r"^[A-Z0-9]{3}$")


def normalize_prefix(value: str | None) -> str:
    prefix = str(value or "").strip().upper()
    if not PREFIX_PATTERN.fullmatch(prefix):
        raise HTTPException(status_code=422, detail="类别编号前缀必须是 3 位大写字母或数字")
    return prefix


def category_prefix(category: Category | None) -> str:
    if category and category.code_prefix:
        return normalize_prefix(category.code_prefix)
    if category:
        preset = DEFAULT_CATEGORY_PREFIXES.get(category.name)
        if not preset:
            raise HTTPException(
                status_code=409,
                detail=f"类别“{category.name}”尚未设置唯一三字符编号前缀",
            )
        return preset
    return "UNC"


def identity_safe_fields(component: Component) -> dict:
    return {
        "owner_user_id": component.owner_user_id,
        "name": component.name,
        "model": component.model,
        "normalized_spec": component.normalized_spec,
        "package": component.package,
        "category_name": component.category.name if component.category else "未分类",
        "lcsc_number": component.lcsc_number,
        "datasheet_url": component.datasheet_url,
    }


def refresh_identity_snapshot(identity: ComponentIdentityRegistry, component: Component) -> None:
    for field, value in identity_safe_fields(component).items():
        setattr(identity, field, value)


def allocate_component_identity(db: Session, component: Component) -> ComponentIdentityRegistry:
    if not component.id:
        db.flush()
    existing = (
        db.query(ComponentIdentityRegistry)
        .filter(ComponentIdentityRegistry.component_id == component.id)
        .first()
    )
    if existing:
        refresh_identity_snapshot(existing, component)
        component.warehouse_code = existing.code
        return existing
    if component.category and not component.category.code_prefix:
        seed_category_prefixes(db)
    prefix = category_prefix(component.category)
    identity = ComponentIdentityRegistry(
        component_id=component.id,
        prefix=prefix,
        legacy_code=component.warehouse_code,
        status="active",
        **identity_safe_fields(component),
    )
    db.add(identity)
    db.flush()
    identity.code = f"{prefix}-{identity.sequence_number:08d}"
    component.warehouse_code = identity.code
    if component.category:
        component.category.code_prefix = prefix
        component.category.code_prefix_locked = True
    return identity


def archive_component_identity(db: Session, component: Component) -> ComponentIdentityRegistry:
    identity = (
        db.query(ComponentIdentityRegistry)
        .filter(ComponentIdentityRegistry.component_id == component.id)
        .first()
    )
    if not identity:
        identity = allocate_component_identity(db, component)
    refresh_identity_snapshot(identity, component)
    identity.status = "archived"
    identity.archived_at = datetime.utcnow()
    identity.component_id = None
    return identity


def identity_by_code(db: Session, code: str) -> ComponentIdentityRegistry | None:
    normalized = str(code or "").strip().upper()
    if not CODE_PATTERN.fullmatch(normalized):
        return None
    return (
        db.query(ComponentIdentityRegistry)
        .filter(func.upper(ComponentIdentityRegistry.code) == normalized)
        .first()
    )


def public_identity_out(identity: ComponentIdentityRegistry, component: Component | None = None) -> dict:
    source = component
    return {
        "warehouse_code": identity.code,
        "name": source.name if source else identity.name,
        "model": source.model if source else identity.model,
        "normalized_spec": source.normalized_spec if source else identity.normalized_spec,
        "package": source.package if source else identity.package,
        "category": (
            source.category.name
            if source and source.category
            else identity.category_name
        ),
        "category_color": source.category.color if source and source.category else None,
        "lcsc_number": source.lcsc_number if source else identity.lcsc_number,
        "datasheet_url": source.datasheet_url if source else identity.datasheet_url,
        "archived": identity.status == "archived",
        "updated_at": source.updated_at if source else identity.archived_at or identity.created_at,
    }


def set_category_prefix(db: Session, category: Category, value: str) -> Category:
    raise HTTPException(status_code=403, detail="类别编号由系统自动生成，不能手工修改")


def generated_category_prefix(name: str, used: set[str]) -> str:
    preset = DEFAULT_CATEGORY_PREFIXES.get(str(name or "").strip())
    if preset and preset not in used:
        return preset
    ascii_letters = "".join(character for character in str(name or "").upper() if "A" <= character <= "Z")
    if len(ascii_letters) >= 3 and ascii_letters[:3] not in used:
        return ascii_letters[:3]
    digest = int(hashlib.sha256(str(name or "").encode("utf-8")).hexdigest()[:10], 16)
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUV" + "W" + "XYZ"
    for offset in range(36 * 36):
        value = (digest + offset) % (36 * 36)
        candidate = f"X{alphabet[value // 36]}{alphabet[value % 36]}"
        if candidate not in used:
            return candidate
    raise HTTPException(status_code=409, detail="没有可用的类别编号前缀，请先合并重复类别")


def seed_category_prefixes(db: Session) -> None:
    used = {
        value
        for (value,) in db.query(Category.code_prefix).filter(Category.code_prefix.isnot(None)).all()
        if value
    }
    for category in db.query(Category).order_by(Category.id.asc()).all():
        if category.code_prefix:
            desired = DEFAULT_CATEGORY_PREFIXES.get(category.name)
            identity_count = (
                db.query(ComponentIdentityRegistry)
                .filter(ComponentIdentityRegistry.category_name == category.name)
                .count()
            )
            if (
                desired
                and desired != category.code_prefix
                and not category.code_prefix_locked
                and identity_count == 0
                and desired not in used
            ):
                used.discard(category.code_prefix)
                category.code_prefix = desired
                used.add(desired)
            category.code_prefix_locked = True
            continue
        candidate = generated_category_prefix(category.name, used)
        category.code_prefix = candidate
        category.code_prefix_locked = True
        used.add(candidate)


def run_component_identity_migration(db: Session) -> int:
    if db.get(AppMigration, V060_COMPONENT_IDENTITIES):
        return 0
    seed_category_prefixes(db)
    migrated = 0
    for component in (
        db.query(Component)
        .filter(Component.revoked_at.is_(None))
        .order_by(Component.id.asc())
        .all()
    ):
        allocate_component_identity(db, component)
        if (component.category and component.category.name in {"开发板", "显示模块"}):
            component.low_stock_exempt = True
        migrated += 1
    db.flush()
    identities = {
        row.component_id: row
        for row in db.query(ComponentIdentityRegistry)
        .filter(ComponentIdentityRegistry.component_id.isnot(None))
        .all()
    }
    identities_by_legacy = {
        row.legacy_code: row
        for row in db.query(ComponentIdentityRegistry)
        .filter(
            ComponentIdentityRegistry.legacy_code.isnot(None),
            ComponentIdentityRegistry.legacy_code != "",
        )
        .all()
    }
    for item in db.query(CompetitionLibraryComponent).all():
        identity = identities.get(item.cw_component_id) or identities_by_legacy.get(
            item.warehouse_code_snapshot
        )
        if identity:
            item.warehouse_code_snapshot = identity.code
            if item.frozen_snapshot_json:
                try:
                    snapshot = json.loads(item.frozen_snapshot_json)
                except json.JSONDecodeError:
                    snapshot = {}
                snapshot["warehouse_code"] = identity.code
                item.frozen_snapshot_json = json.dumps(snapshot, ensure_ascii=False, default=str)
    db.add(
        AppMigration(
            key=V060_COMPONENT_IDENTITIES,
            detail=(
                f"重新编号 {migrated} 个器件为类别三字符前缀和全局八位序号；"
                "旧编号仅保存在 component_identity_registry.legacy_code 中且不再解析。"
            ),
        )
    )
    db.commit()
    return migrated
