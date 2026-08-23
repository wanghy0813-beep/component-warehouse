from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
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


class PersonalProjectV2(Base):
    """Clean personal-project aggregate introduced in v1.3.

    The V2 aggregate intentionally does not share identifiers or relationships
    with the legacy ``projects`` table. Team projects continue to use the
    legacy model through their own API surface.
    """

    __tablename__ = "personal_projects_v2"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    project_code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="planning", nullable=False, index=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, index=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), index=True)


class PersonalProjectVersionV2(Base):
    __tablename__ = "personal_project_versions_v2"
    __table_args__ = (
        UniqueConstraint("project_id", "sequence_number", name="uq_personal_project_v2_version_sequence"),
        UniqueConstraint("project_id", "version_code", name="uq_personal_project_v2_version_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("personal_projects_v2.id"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    version_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="designing", nullable=False, index=True)
    change_summary: Mapped[str | None] = mapped_column(Text)
    active_fabrication_revision_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PersonalProjectStatusEventV2(Base):
    __tablename__ = "personal_project_status_events_v2"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("personal_projects_v2.id"), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(40), index=True)
    to_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), default="web", nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PersonalProjectBomItemV2(Base):
    __tablename__ = "personal_project_bom_items_v2"
    __table_args__ = (
        UniqueConstraint("version_id", "component_id", name="uq_personal_project_v2_bom_component"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("personal_projects_v2.id"), nullable=False, index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("personal_project_versions_v2.id"), nullable=False, index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), nullable=False, index=True)
    quantity_per_board: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    designators: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PersonalProjectBoardV2(Base):
    __tablename__ = "personal_project_boards_v2"
    __table_args__ = (
        UniqueConstraint("version_id", "board_number", name="uq_personal_project_v2_board_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("personal_projects_v2.id"), nullable=False, index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("personal_project_versions_v2.id"), nullable=False, index=True)
    board_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="assembly", nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PersonalProjectSolderPointV2(Base):
    __tablename__ = "personal_project_solder_points_v2"
    __table_args__ = (
        UniqueConstraint("board_id", "bom_item_id", "designator", name="uq_personal_project_v2_solder_point"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("personal_projects_v2.id"), nullable=False, index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("personal_project_versions_v2.id"), nullable=False, index=True)
    board_id: Mapped[str] = mapped_column(ForeignKey("personal_project_boards_v2.id"), nullable=False, index=True)
    bom_item_id: Mapped[str] = mapped_column(ForeignKey("personal_project_bom_items_v2.id"), nullable=False, index=True)
    designator: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    board_side: Mapped[str | None] = mapped_column(String(12), index=True)
    assembly_placement_id: Mapped[str | None] = mapped_column(String(36), index=True)
    active_for_assembly: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    state_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit_cost_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    soldered_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    lost_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PersonalProjectCostEventV2(Base):
    __tablename__ = "personal_project_cost_events_v2"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("personal_projects_v2.id"), nullable=False, index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("personal_project_versions_v2.id"), nullable=False, index=True)
    board_id: Mapped[str | None] = mapped_column(ForeignKey("personal_project_boards_v2.id"), index=True)
    bom_item_id: Mapped[str | None] = mapped_column(ForeignKey("personal_project_bom_items_v2.id"), index=True)
    solder_point_id: Mapped[str | None] = mapped_column(ForeignKey("personal_project_solder_points_v2.id"), index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    unpriced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    reversal_of_event_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PersonalProjectExpenseV2(Base):
    __tablename__ = "personal_project_expenses_v2"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("personal_projects_v2.id"), nullable=False, index=True)
    version_id: Mapped[str | None] = mapped_column(ForeignKey("personal_project_versions_v2.id"), index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    vendor: Mapped[str | None] = mapped_column(String(200), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PersonalProjectRiskV2(Base):
    __tablename__ = "personal_project_risks_v2"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("personal_projects_v2.id"), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), default="medium", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PersonalProjectFileV2(Base):
    __tablename__ = "personal_project_files_v2"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("personal_projects_v2.id"), nullable=False, index=True)
    version_id: Mapped[str | None] = mapped_column(ForeignKey("personal_project_versions_v2.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(300), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(600), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PersonalProjectFabricationRevisionV2(Base):
    """A parsed manufacturing-package revision scoped to one V2 PCB version."""

    __tablename__ = "personal_project_fabrication_revisions_v2"
    __table_args__ = (
        UniqueConstraint("version_id", "revision_number", name="uq_personal_project_v2_fabrication_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("personal_projects_v2.id"), nullable=False, index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("personal_project_versions_v2.id"), nullable=False, index=True)
    source_asset_id: Mapped[str] = mapped_column(ForeignKey("eda_assets.id"), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    detected_profile: Mapped[str | None] = mapped_column(String(40), index=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mapping_json: Mapped[str | None] = mapped_column(Text)
    summary_json: Mapped[str | None] = mapped_column(Text)
    warning_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    bounds_json: Mapped[str | None] = mapped_column(Text)
    calibration_json: Mapped[str | None] = mapped_column(Text)
    ai_assisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PersonalProjectFabricationLayerV2(Base):
    __tablename__ = "personal_project_fabrication_layers_v2"
    __table_args__ = (
        UniqueConstraint("revision_id", "source_name", name="uq_personal_project_v2_fabrication_layer"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("personal_project_fabrication_revisions_v2.id"), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(300), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(12), default="both", nullable=False, index=True)
    svg_asset_id: Mapped[str | None] = mapped_column(ForeignKey("eda_assets.id"), index=True)
    svg_markup: Mapped[str | None] = mapped_column(Text)
    bounds_json: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PersonalProjectAssemblyPlacementV2(Base):
    __tablename__ = "personal_project_assembly_placements_v2"
    __table_args__ = (
        UniqueConstraint("revision_id", "board_side", "designator_key", name="uq_personal_project_v2_placement"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("personal_project_fabrication_revisions_v2.id"), nullable=False, index=True)
    bom_item_id: Mapped[str | None] = mapped_column(ForeignKey("personal_project_bom_items_v2.id"), index=True)
    designator: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    designator_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    board_side: Mapped[str] = mapped_column(String(12), default="top", nullable=False, index=True)
    x_mm: Mapped[float | None] = mapped_column(Float)
    y_mm: Mapped[float | None] = mapped_column(Float)
    rotation_deg: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    source_x_mm: Mapped[float | None] = mapped_column(Float)
    source_y_mm: Mapped[float | None] = mapped_column(Float)
    source_rotation_deg: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    source_board_side: Mapped[str] = mapped_column(String(12), default="top", nullable=False)
    value: Mapped[str | None] = mapped_column(String(200))
    footprint: Mapped[str | None] = mapped_column(String(200))
    model: Mapped[str | None] = mapped_column(String(300))
    dnp: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    positioned: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    match_status: Mapped[str] = mapped_column(String(32), default="unmatched", nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), default="cpl", nullable=False, index=True)
    confidence: Mapped[str] = mapped_column(String(20), default="deterministic", nullable=False, index=True)
    manually_adjusted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PersonalProjectAssemblyOperationV2(Base):
    __tablename__ = "personal_project_assembly_operations_v2"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_personal_project_v2_assembly_operation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("personal_projects_v2.id"), nullable=False, index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("personal_project_versions_v2.id"), nullable=False, index=True)
    board_id: Mapped[str] = mapped_column(ForeignKey("personal_project_boards_v2.id"), nullable=False, index=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    point_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str] = mapped_column(Text, nullable=False)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    undone_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


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
    start_date: Mapped[date | None] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, index=True)
    active_pcb_version_id: Mapped[int | None] = mapped_column(Integer, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
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
    active_fabrication_revision_id: Mapped[str | None] = mapped_column(String(36), index=True)
    public_assembly_view_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
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
    fabrication_revisions: Mapped[list["ProjectFabricationRevision"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectFabricationRevision.revision_number",
    )
    pcb_versions: Mapped[list["ProjectPcbVersion"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectPcbVersion.sequence_number",
    )


class ProjectPcbVersion(Base):
    __tablename__ = "project_pcb_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_code", name="uq_project_pcb_version_code"),
        UniqueConstraint("project_id", "sequence_number", name="uq_project_pcb_version_sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    version_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="designing", index=True)
    change_summary: Mapped[str | None] = mapped_column(Text)
    active_fabrication_revision_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    project: Mapped[Project] = relationship(back_populates="pcb_versions", foreign_keys=[project_id])


class ProjectCodeAlias(Base):
    __tablename__ = "project_code_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    old_code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class ProjectStatusEvent(Base):
    __tablename__ = "project_status_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(40), index=True)
    to_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="web", index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class ProjectExpense(Base):
    __tablename__ = "project_expenses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    pcb_version_id: Mapped[int | None] = mapped_column(ForeignKey("project_pcb_versions.id"), index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    occurred_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    vendor: Mapped[str | None] = mapped_column(String(200), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    attachment_asset_id: Mapped[str | None] = mapped_column(ForeignKey("eda_assets.id"), index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ProjectMaterialCostEvent(Base):
    __tablename__ = "project_material_cost_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    pcb_version_id: Mapped[int | None] = mapped_column(ForeignKey("project_pcb_versions.id"), index=True)
    board_id: Mapped[int | None] = mapped_column(ForeignKey("project_boards.id"), index=True)
    bom_item_id: Mapped[int | None] = mapped_column(ForeignKey("project_bom_items.id"), index=True)
    solder_point_id: Mapped[int | None] = mapped_column(ForeignKey("project_bom_solder_points.id"), index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    unpriced: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_operation_id: Mapped[str | None] = mapped_column(String(36), index=True)
    reversal_of_event_id: Mapped[str | None] = mapped_column(String(36), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class ProjectBoard(Base):
    __tablename__ = "project_boards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    pcb_version_id: Mapped[int | None] = mapped_column(ForeignKey("project_pcb_versions.id"), index=True)
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
    pcb_version_id: Mapped[int | None] = mapped_column(ForeignKey("project_pcb_versions.id"), index=True)
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
    designator_key: Mapped[str | None] = mapped_column(String(80), index=True)
    board_side: Mapped[str | None] = mapped_column(String(12), index=True)
    assembly_placement_id: Mapped[str | None] = mapped_column(String(36), index=True)
    active_for_assembly: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    state_version: Mapped[int] = mapped_column(Integer, default=1)
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


class ProjectFabricationRevision(Base):
    __tablename__ = "project_fabrication_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "revision_number", name="uq_project_fabrication_revision_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    pcb_version_id: Mapped[int | None] = mapped_column(ForeignKey("project_pcb_versions.id"), index=True)
    source_asset_id: Mapped[str] = mapped_column(ForeignKey("eda_assets.id"), index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    detected_profile: Mapped[str | None] = mapped_column(String(40), index=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mapping_json: Mapped[str | None] = mapped_column(Text)
    summary_json: Mapped[str | None] = mapped_column(Text)
    warning_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    bounds_json: Mapped[str | None] = mapped_column(Text)
    calibration_json: Mapped[str | None] = mapped_column(Text)
    ai_assisted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    project: Mapped[Project] = relationship(back_populates="fabrication_revisions")
    layers: Mapped[list["ProjectFabricationLayer"]] = relationship(
        back_populates="revision", cascade="all, delete-orphan"
    )
    placements: Mapped[list["ProjectAssemblyPlacement"]] = relationship(
        back_populates="revision", cascade="all, delete-orphan"
    )


class ProjectFabricationLayer(Base):
    __tablename__ = "project_fabrication_layers"
    __table_args__ = (
        UniqueConstraint("revision_id", "source_name", name="uq_project_fabrication_layer_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("project_fabrication_revisions.id"), index=True)
    source_name: Mapped[str] = mapped_column(String(300), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(12), default="both", index=True)
    svg_asset_id: Mapped[str | None] = mapped_column(ForeignKey("eda_assets.id"), index=True)
    svg_markup: Mapped[str | None] = mapped_column(Text)
    bounds_json: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    revision: Mapped[ProjectFabricationRevision] = relationship(back_populates="layers")


class ProjectAssemblyPlacement(Base):
    __tablename__ = "project_assembly_placements"
    __table_args__ = (
        UniqueConstraint("revision_id", "board_side", "designator_key", name="uq_project_placement_refdes"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("project_fabrication_revisions.id"), index=True)
    bom_item_id: Mapped[int | None] = mapped_column(ForeignKey("project_bom_items.id"), index=True)
    designator: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    designator_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    board_side: Mapped[str] = mapped_column(String(12), default="top", index=True)
    x_mm: Mapped[float | None] = mapped_column(Float)
    y_mm: Mapped[float | None] = mapped_column(Float)
    rotation_deg: Mapped[float] = mapped_column(Float, default=0)
    source_x_mm: Mapped[float | None] = mapped_column(Float)
    source_y_mm: Mapped[float | None] = mapped_column(Float)
    source_rotation_deg: Mapped[float] = mapped_column(Float, default=0)
    source_board_side: Mapped[str] = mapped_column(String(12), default="top")
    value: Mapped[str | None] = mapped_column(String(200))
    footprint: Mapped[str | None] = mapped_column(String(200))
    model: Mapped[str | None] = mapped_column(String(300))
    dnp: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    positioned: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    match_status: Mapped[str] = mapped_column(String(32), default="unmatched", index=True)
    source: Mapped[str] = mapped_column(String(32), default="cpl", index=True)
    confidence: Mapped[str] = mapped_column(String(20), default="deterministic", index=True)
    manually_adjusted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    revision: Mapped[ProjectFabricationRevision] = relationship(back_populates="placements")


class ProjectAssemblyOperation(Base):
    __tablename__ = "project_assembly_operations"
    __table_args__ = (
        UniqueConstraint("project_id", "idempotency_key", name="uq_project_assembly_operation_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    board_id: Mapped[int] = mapped_column(ForeignKey("project_boards.id"), index=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    point_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str] = mapped_column(Text, nullable=False)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    inventory_source_user_ids_json: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    undo_of_operation_id: Mapped[str | None] = mapped_column(String(36), index=True)
    undone_by_operation_id: Mapped[str | None] = mapped_column(String(36), index=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    undone_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class ProjectAssemblyLossEvent(Base):
    __tablename__ = "project_assembly_loss_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    solder_point_id: Mapped[int] = mapped_column(ForeignKey("project_bom_solder_points.id"), index=True)
    operation_id: Mapped[str | None] = mapped_column(ForeignKey("project_assembly_operations.id"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    stock_applied: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    inventory_delta: Mapped[int] = mapped_column(Integer, default=-1)
    prior_soldered: Mapped[bool] = mapped_column(Boolean, default=False)
    prior_stock_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    reversed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class ProjectBomImportBatch(Base):
    __tablename__ = "project_bom_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    pcb_version_id: Mapped[int | None] = mapped_column(ForeignKey("project_pcb_versions.id"), index=True)
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
    pcb_version_id: Mapped[int | None] = mapped_column(ForeignKey("project_pcb_versions.id"), index=True)
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


class SyncDevice(Base):
    __tablename__ = "sync_devices"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "client_id", "installation_id_hash", name="uq_sync_device_installation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    installation_id_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    installation_hint: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    platform: Mapped[str] = mapped_column(String(80), default="windows-x64", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False, index=True)
    last_cursor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_clock_offset_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SyncEntity(Base):
    __tablename__ = "sync_entities"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "entity_type", "local_id", name="uq_sync_entity_local"),
    )

    entity_uid: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    local_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    field_times_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    tombstone: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), index=True)


class SyncTransaction(Base):
    __tablename__ = "sync_transactions"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "event_id", name="uq_sync_transaction_event"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("sync_devices.id"), index=True)
    base_cursor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    client_created_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    server_received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    status: Mapped[str] = mapped_column(String(24), default="accepted", nullable=False, index=True)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class SyncChange(Base):
    __tablename__ = "sync_changes"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "event_id", name="uq_sync_change_event"),
    )

    cursor: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("sync_transactions.id"), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("sync_devices.id"), index=True)
    entity_uid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(24), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    fields_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    refs_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    field_times_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    attachments_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class SyncConflict(Base):
    __tablename__ = "sync_conflicts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("sync_devices.id"), index=True)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("sync_transactions.id"), nullable=False, index=True)
    entity_uid: Mapped[str | None] = mapped_column(String(36), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(100), index=True)
    reason: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    conflict_fields_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    server_version_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    client_version_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    dependencies_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="open", nullable=False, index=True)
    resolution: Mapped[str | None] = mapped_column(String(24), index=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class SyncBlob(Base):
    __tablename__ = "sync_blobs"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(160))
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    reference_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_referenced_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class SyncBlobUpload(Base):
    __tablename__ = "sync_blob_uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("sync_devices.id"), nullable=False, index=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, default=4 * 1024 * 1024, nullable=False)
    received_chunks_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    temp_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="uploading", nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
