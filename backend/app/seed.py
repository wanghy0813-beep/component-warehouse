from sqlalchemy.orm import Session

from .models import Category
from .services.hardware_categories import HARDWARE_CATEGORIES


DEFAULT_CATEGORIES = [item.name for item in HARDWARE_CATEGORIES]

DEFAULT_CATEGORY_COLORS = {item.name: item.color for item in HARDWARE_CATEGORIES}


def seed_categories(db: Session):
    existing = {category.name: category for category in db.query(Category).all()}
    used_prefixes = {category.code_prefix for category in existing.values() if category.code_prefix}
    for name in DEFAULT_CATEGORIES:
        definition = next(item for item in HARDWARE_CATEGORIES if item.name == name)
        if name not in existing:
            prefix = definition.prefix if definition.prefix not in used_prefixes else None
            db.add(Category(name=name, color=definition.color, code_prefix=prefix, code_prefix_locked=bool(prefix)))
            if prefix:
                used_prefixes.add(prefix)
        elif not existing[name].color or existing[name].color == "#eef6ff":
            existing[name].color = DEFAULT_CATEGORY_COLORS.get(name)
        if name in existing and not existing[name].code_prefix and definition.prefix not in used_prefixes:
            existing[name].code_prefix = definition.prefix
            existing[name].code_prefix_locked = True
            used_prefixes.add(definition.prefix)
    db.commit()
