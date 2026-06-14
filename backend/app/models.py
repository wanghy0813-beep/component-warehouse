from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    color: Mapped[str | None] = mapped_column(String(40), default="#eef6ff")

    components: Mapped[list["Component"]] = relationship(back_populates="category")


class Component(Base):
    __tablename__ = "components"
    __table_args__ = (
        UniqueConstraint("lcsc_number", name="uq_components_lcsc_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(200), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    parameters: Mapped[str | None] = mapped_column(Text)
    package: Mapped[str | None] = mapped_column(String(120), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str | None] = mapped_column(String(120))
    lcsc_number: Mapped[str | None] = mapped_column(String(120), index=True)
    tags: Mapped[str | None] = mapped_column(String(300), index=True)
    source_title: Mapped[str | None] = mapped_column(Text)
    part_family: Mapped[str | None] = mapped_column(String(40), default="component", index=True)
    count_mode: Mapped[str | None] = mapped_column(String(40), default="exact", index=True)
    normalized_spec: Mapped[str | None] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(40), default="in_stock", index=True)
    location: Mapped[str | None] = mapped_column(String(200), index=True)
    remark: Mapped[str | None] = mapped_column(Text)
    datasheet_url: Mapped[str | None] = mapped_column(String(500))
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_usage: Mapped[str | None] = mapped_column(Text)
    ai_risk_notes: Mapped[str | None] = mapped_column(Text)
    ai_pcb_notes: Mapped[str | None] = mapped_column(Text)
    ai_substitutes: Mapped[str | None] = mapped_column(Text)
    ai_tags: Mapped[str | None] = mapped_column(String(500), index=True)
    ai_confidence: Mapped[str | None] = mapped_column(String(40), index=True)
    ai_cache_key: Mapped[str | None] = mapped_column(String(80), index=True)
    ai_status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    ai_error: Mapped[str | None] = mapped_column(Text)
    ai_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    is_hand_solder_friendly: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_power_component: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_signal_component: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_high_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_high_voltage: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_common: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    category: Mapped[Category | None] = relationship(back_populates="components")
    bom_items: Mapped[list["ProjectBomItem"]] = relationship(back_populates="component")
    knowledge_cards: Mapped[list["AiKnowledgeCard"]] = relationship(back_populates="component")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="active")
    ai_bom_analysis: Mapped[str | None] = mapped_column(Text)
    ai_bom_cache_key: Mapped[str | None] = mapped_column(String(80), index=True)
    ai_bom_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    bom_match_total: Mapped[int] = mapped_column(Integer, default=0)
    bom_match_matched: Mapped[int] = mapped_column(Integer, default=0)
    bom_match_review: Mapped[int] = mapped_column(Integer, default=0)
    bom_match_missing: Mapped[int] = mapped_column(Integer, default=0)
    bom_match_missing_items: Mapped[str | None] = mapped_column(Text)
    bom_match_rows: Mapped[str | None] = mapped_column(Text)
    bom_match_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    bom_items: Mapped[list["ProjectBomItem"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class ProjectBomItem(Base):
    __tablename__ = "project_bom_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    required_quantity: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40), default="reserved", index=True)
    remark: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="bom_items")
    component: Mapped[Component] = relationship(back_populates="bom_items")


class ProjectBomImportBatch(Base):
    __tablename__ = "project_bom_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    source_file: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_imported_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ProjectBomImportRow(Base):
    __tablename__ = "project_bom_import_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("project_bom_import_batches.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    source_row: Mapped[int | None] = mapped_column(Integer)
    designator: Mapped[str | None] = mapped_column(String(300))
    required_quantity: Mapped[int] = mapped_column(Integer, default=1)
    comment: Mapped[str | None] = mapped_column(Text)
    footprint: Mapped[str | None] = mapped_column(String(200))
    value: Mapped[str | None] = mapped_column(String(200))
    manufacturer_part: Mapped[str | None] = mapped_column(String(300))
    supplier_part: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), default="missing", index=True)
    selected_component_id: Mapped[int | None] = mapped_column(ForeignKey("components.id"), index=True)
    match_confidence: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str | None] = mapped_column(Text)
    ai_reason: Mapped[str | None] = mapped_column(Text)
    ai_confidence: Mapped[str | None] = mapped_column(String(40))
    ai_error: Mapped[str | None] = mapped_column(Text)
    missing_description: Mapped[str | None] = mapped_column(Text)
    missing_reason: Mapped[str | None] = mapped_column(Text)
    lcsc_search_keyword: Mapped[str | None] = mapped_column(String(300))
    lcsc_search_url: Mapped[str | None] = mapped_column(Text)
    auto_imported: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_import_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ProjectBomImportCandidate(Base):
    __tablename__ = "project_bom_import_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    import_row_id: Mapped[int] = mapped_column(ForeignKey("project_bom_import_rows.id"), index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    match_type: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(Text)
    flags: Mapped[str | None] = mapped_column(String(300))
    available_quantity: Mapped[int] = mapped_column(Integer, default=0)
    shortage_quantity: Mapped[int] = mapped_column(Integer, default=0)
    enough: Mapped[bool] = mapped_column(Boolean, default=False)
    rank: Mapped[int] = mapped_column(Integer, default=0)


class ImportRecord(Base):
    __tablename__ = "import_records"
    __table_args__ = (
        UniqueConstraint("order_number", "lcsc_number", name="uq_import_records_order_lcsc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_number: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    lcsc_number: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey("components.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    source_file: Mapped[str | None] = mapped_column(String(300))
    source_row: Mapped[int | None] = mapped_column(Integer)
    raw_data: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey("components.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    quantity_delta: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class AiTask(Base):
    __tablename__ = "ai_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    input_hash: Mapped[str | None] = mapped_column(String(80), index=True)
    result_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class AiKnowledgeCard(Base):
    __tablename__ = "ai_knowledge_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey("components.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str | None] = mapped_column(String(500), index=True)
    source_type: Mapped[str] = mapped_column(String(80), default="ai", index=True)
    confidence: Mapped[str | None] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    component: Mapped[Component | None] = relationship(back_populates="knowledge_cards")
