from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    color: Mapped[str | None] = mapped_column(String(40), default="#eef6ff")
    code_prefix: Mapped[str | None] = mapped_column(String(3), unique=True, index=True)
    code_prefix_locked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    components: Mapped[list["Component"]] = relationship(back_populates="category")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=False)
    account_id: Mapped[str | None] = mapped_column(String(36), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    nickname: Mapped[str | None] = mapped_column(String(80))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    # Legacy column kept for SQLite compatibility. Authentication is handled by the configured account provider.
    password_hash: Mapped[str | None] = mapped_column(String(300))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class IntegrationAccessToken(Base):
    __tablename__ = "integration_access_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    token_prefix: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    scopes: Mapped[str] = mapped_column(String(200), default="inventory:read")
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class IntegrationOperation(Base):
    __tablename__ = "integration_operations"
    __table_args__ = (
        UniqueConstraint("access_token_id", "idempotency_key", name="uq_integration_operation_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    access_token_id: Mapped[str | None] = mapped_column(ForeignKey("integration_access_tokens.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending_approval", index=True)
    risk_level: Mapped[str] = mapped_column(String(20), default="normal", index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    preview_json: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    inverse_json: Mapped[str | None] = mapped_column(Text)
    precondition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    approval_expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    undo_expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    undo_of_operation_id: Mapped[str | None] = mapped_column(String(36), index=True)
    undone_by_operation_id: Mapped[str | None] = mapped_column(String(36), index=True)
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Component(Base):
    __tablename__ = "components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    warehouse_code: Mapped[str | None] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(200), index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    parameters: Mapped[str | None] = mapped_column(Text)
    package: Mapped[str | None] = mapped_column(String(120), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    occupied_quantity: Mapped[int] = mapped_column(Integer, default=0)
    average_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
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
    competition_name: Mapped[str | None] = mapped_column(String(120), index=True)
    competition_category: Mapped[str | None] = mapped_column(String(80), index=True)
    priority: Mapped[str | None] = mapped_column(String(20), index=True)
    target_quantity: Mapped[int] = mapped_column(Integer, default=0)
    safety_quantity: Mapped[int] = mapped_column(Integer, default=0)
    low_stock_exempt: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    manual_stock_status: Mapped[str | None] = mapped_column(String(40), index=True)
    usability_status: Mapped[str | None] = mapped_column(String(40), index=True)
    verify_status: Mapped[str | None] = mapped_column(String(40), index=True)
    location_code: Mapped[str | None] = mapped_column(String(120), index=True)
    buy_url: Mapped[str | None] = mapped_column(String(500))
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
    first_stocked_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_stocked_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    is_hand_solder_friendly: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_power_component: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_signal_component: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_high_current: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_high_voltage: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_common: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)

    category: Mapped[Category | None] = relationship(back_populates="components")
    bom_items: Mapped[list["ProjectBomItem"]] = relationship(back_populates="component")
    knowledge_cards: Mapped[list["AiKnowledgeCard"]] = relationship(back_populates="component")


class ComponentIdentityRegistry(Base):
    __tablename__ = "component_identity_registry"
    __table_args__ = {"sqlite_autoincrement": True}

    sequence_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    component_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    code: Mapped[str | None] = mapped_column(String(12), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(3), index=True)
    legacy_code: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    owner_user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    model: Mapped[str | None] = mapped_column(String(200))
    normalized_spec: Mapped[str | None] = mapped_column(String(160))
    package: Mapped[str | None] = mapped_column(String(120))
    category_name: Mapped[str | None] = mapped_column(String(80))
    lcsc_number: Mapped[str | None] = mapped_column(String(120))
    datasheet_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    scope_type: Mapped[str] = mapped_column(String(20), default="personal", index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    team_library_id: Mapped[str | None] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    project_code: Mapped[str | None] = mapped_column(String(80), index=True)
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
    boards: Mapped[list["ProjectBoard"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectBoard.board_index",
    )


class ProjectBoard(Base):
    __tablename__ = "project_boards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    board_index: Mapped[int] = mapped_column(Integer, default=1, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    note: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    project: Mapped[Project] = relationship(back_populates="boards")
    solder_points: Mapped[list["ProjectBomSolderPoint"]] = relationship(back_populates="board")


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
    solder_points: Mapped[list["ProjectBomSolderPoint"]] = relationship(
        back_populates="bom_item",
        cascade="all, delete-orphan",
        order_by="ProjectBomSolderPoint.id",
    )


class ProjectBomSolderPoint(Base):
    __tablename__ = "project_bom_solder_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    bom_item_id: Mapped[int] = mapped_column(ForeignKey("project_bom_items.id"), index=True)
    board_id: Mapped[int | None] = mapped_column(ForeignKey("project_boards.id"), index=True)
    designator: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    bom_value: Mapped[str | None] = mapped_column(String(200))
    bom_model: Mapped[str | None] = mapped_column(String(300))
    bom_footprint: Mapped[str | None] = mapped_column(String(200))
    soldered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    soldered_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    stock_applied: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    lost: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    lost_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    loss_stock_applied: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    loss_note: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    bom_item: Mapped[ProjectBomItem] = relationship(back_populates="solder_points")
    board: Mapped[ProjectBoard | None] = relationship(back_populates="solder_points")


class ProjectBomImportBatch(Base):
    __tablename__ = "project_bom_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    source_file: Mapped[str | None] = mapped_column(String(300))
    source_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    field_mapping_json: Mapped[str | None] = mapped_column(Text)
    analysis_json: Mapped[str | None] = mapped_column(Text)
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


class OrderImportBatch(Base):
    __tablename__ = "order_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    source_file: Mapped[str | None] = mapped_column(String(300))
    order_number: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    merged_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    already_imported_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_pending_count: Mapped[int] = mapped_column(Integer, default=0)
    rollback_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class OrderImportLine(Base):
    __tablename__ = "order_import_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("order_import_batches.id"), index=True)
    import_record_id: Mapped[int | None] = mapped_column(ForeignKey("import_records.id"), index=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey("components.id"), index=True)
    source_row: Mapped[int | None] = mapped_column(Integer)
    order_number: Mapped[str | None] = mapped_column(String(120), index=True)
    lcsc_number: Mapped[str | None] = mapped_column(String(120), index=True)
    operation: Mapped[str] = mapped_column(String(40), index=True)
    quantity_delta: Mapped[int] = mapped_column(Integer, default=0)
    previous_component: Mapped[str | None] = mapped_column(Text)
    row_data: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PriceImportBatch(Base):
    __tablename__ = "price_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_file: Mapped[str | None] = mapped_column(String(300))
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_count: Mapped[int] = mapped_column(Integer, default=0)
    canceled_count: Mapped[int] = mapped_column(Integer, default=0)
    rollback_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class ComponentPriceEntry(Base):
    __tablename__ = "component_price_entries"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "order_number", "lcsc_number", name="uq_component_price_owner_order_lcsc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    order_number: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    lcsc_number: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    order_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    ordered_at: Mapped[str | None] = mapped_column(String(40), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    merchandise_total: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal("0"))
    allocated_shipping: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal("0"))
    landed_total: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal("0"))
    source_file: Mapped[str | None] = mapped_column(String(300))
    source_row: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PriceImportLine(Base):
    __tablename__ = "price_import_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("price_import_batches.id"), index=True)
    price_entry_id: Mapped[int | None] = mapped_column(ForeignKey("component_price_entries.id"), index=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey("components.id"), index=True)
    source_row: Mapped[int | None] = mapped_column(Integer)
    order_number: Mapped[str | None] = mapped_column(String(120), index=True)
    lcsc_number: Mapped[str | None] = mapped_column(String(120), index=True)
    operation: Mapped[str] = mapped_column(String(40), index=True)
    previous_entry: Mapped[str | None] = mapped_column(Text)
    previous_average_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    row_data: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class ImportRecord(Base):
    __tablename__ = "import_records"
    __table_args__ = (
        UniqueConstraint("order_number", "lcsc_number", name="uq_import_records_order_lcsc"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("order_import_batches.id"), index=True)
    order_number: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    lcsc_number: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey("components.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    source_file: Mapped[str | None] = mapped_column(String(300))
    source_row: Mapped[int | None] = mapped_column(Integer)
    raw_data: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AppMigration(Base):
    __tablename__ = "app_migrations"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    detail: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class CompetitionLibrary(Base):
    __tablename__ = "competition_libraries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    competition_type: Mapped[str | None] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    creator_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class CompetitionLibraryMember(Base):
    __tablename__ = "competition_library_members"
    __table_args__ = (
        UniqueConstraint("library_id", "user_id", name="uq_competition_library_member"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    library_id: Mapped[str] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(24), default="member", index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    joined_invite_id: Mapped[str | None] = mapped_column(String(36), index=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    blocked_invite_id: Mapped[str | None] = mapped_column(String(36), index=True)


class CompetitionInvite(Base):
    __tablename__ = "competition_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    library_id: Mapped[str] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class CompetitionLibraryComponent(Base):
    __tablename__ = "competition_library_components"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    library_id: Mapped[str] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    cw_component_id: Mapped[int | None] = mapped_column(ForeignKey("components.id"), index=True)
    source_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    sync_status: Mapped[str] = mapped_column(String(24), default="live", index=True)
    warehouse_code_snapshot: Mapped[str | None] = mapped_column(String(80), index=True)
    frozen_snapshot_json: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(200), index=True)
    lcsc_number: Mapped[str | None] = mapped_column(String(120), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str | None] = mapped_column(String(200), index=True)
    category: Mapped[str | None] = mapped_column(String(80), index=True)
    tags: Mapped[str | None] = mapped_column(String(300), index=True)
    remark: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    updated_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class CompetitionComponentMarker(Base):
    __tablename__ = "competition_component_markers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    library_id: Mapped[str] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    component_id: Mapped[str] = mapped_column(ForeignKey("competition_library_components.id"), index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#F97316", index=True)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    updated_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class CompetitionPcb(Base):
    __tablename__ = "competition_pcbs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    library_id: Mapped[str] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    pcb_version: Mapped[str | None] = mapped_column(String(80), index=True)
    function_desc: Mapped[str | None] = mapped_column(Text)
    main_chip: Mapped[str | None] = mapped_column(String(160), index=True)
    voltage: Mapped[str | None] = mapped_column(String(80))
    interface_type: Mapped[str | None] = mapped_column(String(160), index=True)
    suitable_task: Mapped[str | None] = mapped_column(String(300), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    location: Mapped[str | None] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(24), default="待确认", index=True)
    repository_url: Mapped[str | None] = mapped_column(String(500))
    schematic_url: Mapped[str | None] = mapped_column(String(500))
    datasheet_url: Mapped[str | None] = mapped_column(String(500))
    front_image_path: Mapped[str | None] = mapped_column(String(500))
    back_image_path: Mapped[str | None] = mapped_column(String(500))
    remark: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    updated_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class CompetitionActivityLog(Base):
    __tablename__ = "competition_activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    library_id: Mapped[str] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    actor_nickname: Mapped[str] = mapped_column(String(80))
    actor_phone_last4: Mapped[str] = mapped_column(String(4))
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class CompetitionAiResult(Base):
    __tablename__ = "competition_ai_results"
    __table_args__ = (
        UniqueConstraint(
            "library_id",
            "query_type",
            "input_hash",
            name="uq_competition_ai_result",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    library_id: Mapped[str] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    query_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    prompt_text: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
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


class SupplierPart(Base):
    __tablename__ = "supplier_parts"
    __table_args__ = (
        UniqueConstraint(
            "scope_type",
            "owner_user_id",
            "team_library_id",
            "supplier",
            "supplier_part_number",
            name="uq_supplier_part_scope_number",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(20), default="personal", index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    team_library_id: Mapped[str | None] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    supplier: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    supplier_part_number: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    purchase_url: Mapped[str | None] = mapped_column(String(1000))
    currency: Mapped[str | None] = mapped_column(String(8), default="CNY")
    unit_price: Mapped[float | None] = mapped_column(Float)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class EdaLibrary(Base):
    __tablename__ = "eda_libraries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(20), default="personal", index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    team_library_id: Mapped[str | None] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(80), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class EdaLibraryVersion(Base):
    __tablename__ = "eda_library_versions"
    __table_args__ = (
        UniqueConstraint("library_id", "version", name="uq_eda_library_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    library_id: Mapped[str] = mapped_column(ForeignKey("eda_libraries.id"), index=True)
    version: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    change_note: Mapped[str | None] = mapped_column(Text)
    compatible_with_previous: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(24), default="raw", index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class EdaAsset(Base):
    __tablename__ = "eda_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(20), default="personal", index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    team_library_id: Mapped[str | None] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    library_version_id: Mapped[str | None] = mapped_column(ForeignKey("eda_library_versions.id"), index=True)
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    original_name: Mapped[str] = mapped_column(String(300), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(700), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str | None] = mapped_column(String(160))
    version_label: Mapped[str | None] = mapped_column(String(80), index=True)
    source_url: Mapped[str | None] = mapped_column(String(1500))
    source_license: Mapped[str | None] = mapped_column(String(200))
    verification_status: Mapped[str] = mapped_column(String(24), default="raw", index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class EdaSymbol(Base):
    __tablename__ = "eda_symbols"
    __table_args__ = (
        UniqueConstraint("library_version_id", "name", name="uq_eda_symbol_version_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    library_version_id: Mapped[str] = mapped_column(ForeignKey("eda_library_versions.id"), index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(24), default="raw", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EdaFootprint(Base):
    __tablename__ = "eda_footprints"
    __table_args__ = (
        UniqueConstraint("library_version_id", "name", name="uq_eda_footprint_version_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    library_version_id: Mapped[str] = mapped_column(ForeignKey("eda_library_versions.id"), index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(24), default="raw", index=True)
    preview_asset_id: Mapped[str | None] = mapped_column(ForeignKey("eda_assets.id"), index=True)
    model_asset_id: Mapped[str | None] = mapped_column(ForeignKey("eda_assets.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EdaComponentBinding(Base):
    __tablename__ = "eda_component_bindings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(20), default="personal", index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    team_library_id: Mapped[str | None] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    library_version_id: Mapped[str | None] = mapped_column(ForeignKey("eda_library_versions.id"), index=True)
    symbol_id: Mapped[str | None] = mapped_column(ForeignKey("eda_symbols.id"), index=True)
    footprint_id: Mapped[str | None] = mapped_column(ForeignKey("eda_footprints.id"), index=True)
    datasheet_asset_id: Mapped[str | None] = mapped_column(ForeignKey("eda_assets.id"), index=True)
    model_asset_id: Mapped[str | None] = mapped_column(ForeignKey("eda_assets.id"), index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    verification_status: Mapped[str] = mapped_column(String(24), default="raw", index=True)
    source: Mapped[str | None] = mapped_column(String(160))
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class EdaVerification(Base):
    __tablename__ = "eda_verifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    binding_id: Mapped[str] = mapped_column(ForeignKey("eda_component_bindings.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    checklist_json: Mapped[str | None] = mapped_column(Text)
    evidence_asset_id: Mapped[str | None] = mapped_column(ForeignKey("eda_assets.id"), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    verified_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class EdaAttachmentLink(Base):
    __tablename__ = "eda_attachment_links"
    __table_args__ = (
        UniqueConstraint("asset_id", "entity_type", "entity_id", name="uq_eda_attachment_link"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("eda_assets.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(40), default="attachment", index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class InventoryLot(Base):
    __tablename__ = "inventory_lots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    source_reference: Mapped[str | None] = mapped_column(String(160), index=True)
    location: Mapped[str | None] = mapped_column(String(200), index=True)
    initial_quantity: Mapped[int] = mapped_column(Integer, default=0)
    remaining_quantity: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class CustomLabelTemplate(Base):
    __tablename__ = "custom_label_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(20), default="personal", index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    team_library_id: Mapped[str | None] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class CustomLabelAsset(Base):
    __tablename__ = "custom_label_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("custom_label_templates.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(240), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class StockMovement(Base):
    __tablename__ = "stock_movements_v2"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    lot_id: Mapped[str | None] = mapped_column(ForeignKey("inventory_lots.id"), index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    movement_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    purchase_line_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(20), default="personal", index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    team_library_id: Mapped[str | None] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    order_number: Mapped[str | None] = mapped_column(String(160), index=True)
    platform: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PurchaseLine(Base):
    __tablename__ = "purchase_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    purchase_order_id: Mapped[str] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey("components.id"), index=True)
    supplier_part_id: Mapped[str | None] = mapped_column(ForeignKey("supplier_parts.id"), index=True)
    receiver_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    ordered_quantity: Mapped[int] = mapped_column(Integer, default=0)
    received_quantity: Mapped[int] = mapped_column(Integer, default=0)
    unit_price: Mapped[float | None] = mapped_column(Float)
    purchase_url: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PurchaseReceipt(Base):
    __tablename__ = "purchase_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    purchase_line_id: Mapped[str] = mapped_column(ForeignKey("purchase_lines.id"), index=True)
    inventory_lot_id: Mapped[str | None] = mapped_column(ForeignKey("inventory_lots.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    received_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    note: Mapped[str | None] = mapped_column(Text)


class RiskIssue(Base):
    __tablename__ = "risk_issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(20), default="personal", index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    team_library_id: Mapped[str | None] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    component_id: Mapped[int | None] = mapped_column(ForeignKey("components.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    risk_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="warning", index=True)
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(40), default="system", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)


class EdaSyncToken(Base):
    __tablename__ = "eda_sync_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(20), default="personal", index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    team_library_id: Mapped[str | None] = mapped_column(ForeignKey("competition_libraries.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    token_prefix: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
