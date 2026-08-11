from sqlalchemy.orm import Session

from .models import Category


DEFAULT_CATEGORIES = [
    "电阻",
    "电容",
    "电感",
    "二极管",
    "三极管",
    "MOS管",
    "芯片",
    "电源",
    "接口",
    "连接件",
    "时钟源",
    "开关",
    "开发板",
    "设备",
    "功能模块",
    "通信模块",
    "显示模块",
    "机电件",
    "散热件",
    "保护器件",
    "传感器",
    "结构件",
    "其他",
]

DEFAULT_CATEGORY_COLORS = {
    "电阻": "#e8f1ff",
    "电容": "#f1e8ff",
    "电感": "#e6fbff",
    "二极管": "#fff2df",
    "三极管": "#e8f7ee",
    "MOS管": "#e4f6ec",
    "芯片": "#e7edff",
    "电源": "#ffe9e7",
    "接口": "#fff7d6",
    "连接件": "#e8fff8",
    "时钟源": "#eef2ff",
    "开关": "#f1f3f5",
    "开发板": "#e8eaee",
    "设备": "#e5edf5",
    "功能模块": "#eaf4ff",
    "通信模块": "#e9f8ff",
    "显示模块": "#f3ecff",
    "机电件": "#fff0e6",
    "散热件": "#e9fbf2",
    "保护器件": "#ffece4",
    "传感器": "#ffeaf5",
    "结构件": "#f4f1ec",
    "其他": "#eef2f7",
}


def seed_categories(db: Session):
    existing = {category.name: category for category in db.query(Category).all()}
    for name in DEFAULT_CATEGORIES:
        if name not in existing:
            db.add(Category(name=name, color=DEFAULT_CATEGORY_COLORS.get(name)))
        elif not existing[name].color or existing[name].color == "#eef6ff":
            existing[name].color = DEFAULT_CATEGORY_COLORS.get(name)
    db.commit()
