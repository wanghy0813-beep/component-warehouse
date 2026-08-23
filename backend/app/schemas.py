from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    color: str | None = None
    code_prefix: str | None = None
    code_prefix_locked: bool = False


class CategoryPrefixUpdate(BaseModel):
    code_prefix: str = Field(min_length=3, max_length=3)


class ComponentBase(BaseModel):
    warehouse_code: str | None = None
    name: str
    model: str | None = None
    manufacturer: str | None = None
    description: str | None = None
    category_id: int | None = None
    parameters: str | None = None
    package: str | None = None
    quantity: int = 0
    average_unit_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=6)
    source: str | None = None
    lcsc_number: str | None = None
    tags: str | None = None
    source_title: str | None = None
    part_family: str | None = "component"
    count_mode: str | None = "exact"
    normalized_spec: str | None = None
    status: str = "in_stock"
    location: str | None = None
    remark: str | None = None
    datasheet_url: str | None = None
    buy_url: str | None = None
    is_hand_solder_friendly: bool = False
    is_power_component: bool = False
    is_signal_component: bool = False
    is_high_current: bool = False
    is_high_voltage: bool = False
    is_common: bool = False
    safety_quantity: int = Field(default=0, ge=0)
    low_stock_exempt: bool = False


class ComponentCreate(ComponentBase):
    pass


class ComponentUpdate(ComponentBase):
    name: str | None = None


class LcscPreviewRequest(BaseModel):
    raw_text: str = Field(min_length=1, max_length=4000)


class LcscPreviewResponse(BaseModel):
    status: Literal["official", "ai_fallback", "parsed_only"]
    draft: dict[str, Any]
    existing_component: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)


class SearchUnitConversion(BaseModel):
    query_value: str
    matched_value: str
    dimension: Literal["capacitance", "inductance", "resistance"]
    dimension_label: str
    label: str


class ComponentOut(ComponentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: CategoryOut | None = None
    reserved_quantity: int = 0
    occupied_quantity: int = 0
    available_quantity: int = 0
    low_stock_warning: bool = False
    ai_summary: str | None = None
    ai_usage: str | None = None
    ai_risk_notes: str | None = None
    ai_pcb_notes: str | None = None
    ai_substitutes: str | None = None
    ai_tags: str | None = None
    ai_confidence: str | None = None
    ai_cache_key: str | None = None
    ai_status: str = "pending"
    ai_error: str | None = None
    ai_updated_at: datetime | None = None
    first_stocked_at: datetime | None = None
    last_stocked_at: datetime | None = None
    last_outbound_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    search_unit_conversion: SearchUnitConversion | None = None


class ComponentCardOut(BaseModel):
    """Compact component representation used by the inventory card stream."""

    id: int
    warehouse_code: str | None = None
    name: str
    model: str | None = None
    category_id: int | None = None
    category: CategoryOut | None = None
    parameters: str | None = None
    package: str | None = None
    quantity: int = 0
    average_unit_price: Decimal | None = None
    source: str | None = None
    lcsc_number: str | None = None
    tags: str | None = None
    source_title: str | None = None
    part_family: str | None = "component"
    normalized_spec: str | None = None
    status: str = "in_stock"
    location: str | None = None
    buy_url: str | None = None
    reserved_quantity: int = 0
    occupied_quantity: int = 0
    available_quantity: int = 0
    low_stock_warning: bool = False
    card_chips: list[dict[str, Any]] = Field(default_factory=list)
    card_usage: str | None = None
    ai_tags: str | None = None
    ai_status: str = "pending"
    search_unit_conversion: SearchUnitConversion | None = None


class ComponentList(BaseModel):
    items: list[ComponentOut]
    total: int


class ComponentUsageRecordOut(BaseModel):
    id: int
    action: str
    action_label: str
    project_id: int | None = None
    project_code: str | None = None
    project_name: str | None = None
    quantity_delta: int | None = None
    designators: list[str] = []
    summary: str
    created_at: datetime | None = None


class ComponentGroup(BaseModel):
    category: CategoryOut | None = None
    items: list[ComponentOut]
    total: int


class ComponentGroupPage(BaseModel):
    groups: list[ComponentGroup]
    total: int
    page: int
    page_size: int
    has_more: bool = False
    category_total: int = 0


class ComponentCardGroup(BaseModel):
    category: CategoryOut | None = None
    items: list[ComponentCardOut]
    total: int


class ComponentCardGroupPage(BaseModel):
    groups: list[ComponentCardGroup]
    total: int
    page: int
    page_size: int
    has_more: bool = False
    category_total: int = 0


class ComponentExportCustomLabel(BaseModel):
    template_id: str
    copies: int = Field(default=1, ge=1, le=40)


class ComponentExportRequest(BaseModel):
    ids: list[int] = []
    all: bool = False
    imported_from: str | None = None
    imported_to: str | None = None
    excluded_categories: list[str] = Field(default_factory=list)
    start_slot: int = Field(default=1, ge=1, le=40)
    copies: int = Field(default=1, ge=1, le=20)
    offset_x_mm: float = Field(default=0, ge=-5, le=5)
    offset_y_mm: float = Field(default=0, ge=-5, le=5)
    safe_margin: bool = True
    calibration: bool = False
    custom_labels: list[ComponentExportCustomLabel] = Field(default_factory=list)
    output_format: str = "html"


class CustomLabelAssetOut(BaseModel):
    id: str
    template_id: str
    file_name: str
    mime_type: str
    sha256: str
    size_bytes: int = 0
    url: str | None = None
    created_at: datetime | None = None


class CustomLabelTemplateBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    content: dict[str, Any] = Field(default_factory=dict)


class CustomLabelTemplateCreate(CustomLabelTemplateBase):
    pass


class CustomLabelTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    content: dict[str, Any] | None = None


class CustomLabelTemplateOut(BaseModel):
    id: str
    scope_type: str
    owner_user_id: int | None = None
    team_library_id: str | None = None
    name: str
    content: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"
    assets: list[CustomLabelAssetOut] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CustomLabelExportRequest(BaseModel):
    template_id: str | None = None
    content: dict[str, Any] | None = None
    start_slot: int = Field(default=1, ge=1, le=40)
    copies: int = Field(default=1, ge=1, le=40)
    offset_x_mm: float = Field(default=0, ge=-5, le=5)
    offset_y_mm: float = Field(default=0, ge=-5, le=5)
    safe_margin: bool = True
    calibration: bool = False


class ProjectBase(BaseModel):
    project_code: str
    name: str
    description: str | None = None
    status: str = "planning"
    start_date: date | None = None
    end_date: date | None = None


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    project_code: str | None = None
    name: str | None = None
    description: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class BomItemCreate(BaseModel):
    component_id: int
    required_quantity: int = Field(default=1, ge=1)
    status: str = "reserved"
    remark: str | None = None


class BomItemUpdate(BaseModel):
    component_id: int | None = None
    required_quantity: int | None = Field(default=None, ge=1)
    status: str | None = None
    remark: str | None = None


class BomSolderPointUpdate(BaseModel):
    soldered: bool
    note: str | None = None


class BomSolderPointBulkUpdate(BaseModel):
    soldered: bool
    point_ids: list[int] | None = None
    note: str | None = None


class BomSolderPointLossUpdate(BaseModel):
    lost: bool
    note: str | None = None


class ProjectBoardOut(BaseModel):
    id: int
    project_id: int
    pcb_version_id: int | None = None
    board_index: int = 1
    name: str
    status: str = "active"
    note: str | None = None
    solder_total: int = 0
    soldered_count: int = 0
    lost_count: int = 0
    pending_count: int = 0
    solder_progress: int = 0
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BomImportRowSelection(BaseModel):
    component_id: int | None = None


class BomMatchCommitItem(BaseModel):
    import_row_id: int | None = None
    component_id: int
    required_quantity: int = Field(default=1, ge=1)
    remark: str | None = None


class BomMatchCommitRequest(BaseModel):
    items: list[BomMatchCommitItem]


class BomMatchCommitResult(BaseModel):
    added: int
    updated: int
    skipped: int


class BomItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pcb_version_id: int | None = None
    component_id: int
    required_quantity: int
    status: str = "reserved"
    remark: str | None = None
    component: ComponentOut
    available_quantity: int
    reserved_quantity: int = 0
    free_quantity: int = 0
    shortage_quantity: int
    enough: bool
    solder_points: list[dict] = Field(default_factory=list)
    soldered_count: int = 0
    solder_total: int = 0
    lost_count: int = 0
    pending_count: int = 0
    solder_progress: int = 0


class ProjectOut(ProjectBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    active_pcb_version_id: int | None = None
    current_version_code: str | None = None
    archived_at: datetime | None = None
    start_week: str | None = None
    end_week: str | None = None
    actual_days: int | None = None
    actual_weeks: float | None = None
    status_label: str | None = None
    cost_summary: dict = Field(default_factory=dict)
    versions: list[dict] = Field(default_factory=list)
    active_fabrication_revision_id: str | None = None
    public_assembly_view_enabled: bool = False
    ai_bom_analysis: str | None = None
    ai_bom_cache_key: str | None = None
    ai_bom_updated_at: datetime | None = None
    bom_match_total: int = 0
    bom_match_matched: int = 0
    bom_match_review: int = 0
    bom_match_missing: int = 0
    bom_match_missing_items: str | None = None
    bom_match_rows: str | None = None
    bom_match_updated_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    boards: list[ProjectBoardOut] = []
    active_board_id: int | None = None
    board_count: int = 0
    soldered_count: int = 0
    solder_total: int = 0
    lost_count: int = 0
    pending_count: int = 0
    solder_progress: int = 0
    bom_items: list[BomItemOut] = []


class ImportPreviewRow(ComponentBase):
    model_config = ConfigDict(extra="allow")
    name: str | None = None
    duplicate: bool = False
    duplicate_component_id: int | None = None
    already_imported: bool = False
    import_key: str | None = None
    suggested_action: str = "create"
    action: str | None = None
    source_row: int = 0
    source_file: str | None = None
    order_number: str | None = None
    brand: str | None = None
    product_type: str | None = None
    unit: str | None = None
    shipping_no: str | None = None
    order_time: str | None = None
    shipment_date: str | None = None
    store_name: str | None = None
    product_link: str | None = None
    category_name: str | None = None
    external_import_key: str | None = None
    ai_confidence: str | None = None
    ai_reason: str | None = None
    order_quantity: str | int | None = None
    component_quantity_per_order: str | int | None = None


class ImportCommitRequest(BaseModel):
    rows: list[ImportPreviewRow]


class ImportCommitResult(BaseModel):
    created: int
    merged: int
    skipped: int
    already_imported: int = 0
    resolved_pending_purchase: int = 0
    batch_id: int | None = None


class OrderImportLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: int
    component_id: int | None = None
    source_row: int | None = None
    order_number: str | None = None
    lcsc_number: str | None = None
    operation: str
    quantity_delta: int = 0
    note: str | None = None
    rolled_back_at: datetime | None = None
    created_at: datetime | None = None


class OrderImportBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_file: str | None = None
    order_number: str | None = None
    status: str
    created_count: int = 0
    merged_count: int = 0
    skipped_count: int = 0
    already_imported_count: int = 0
    resolved_pending_count: int = 0
    rollback_summary: str | None = None
    created_at: datetime | None = None
    rolled_back_at: datetime | None = None
    lines: list[OrderImportLineOut] = []


class ActivityLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    entity_type: str
    entity_id: int | None = None
    component_id: int | None = None
    project_id: int | None = None
    quantity_delta: int | None = None
    summary: str
    detail: str | None = None
    created_at: datetime | None = None


class UsageEventRequest(BaseModel):
    event: str = Field(min_length=3, max_length=80)
    page: str | None = Field(default=None, max_length=160)
    target_type: str | None = Field(default=None, max_length=80)
    target_id: str | int | None = None
    entry: str | None = Field(default=None, max_length=120)
    detail: dict | None = None
    viewport_width: int | None = Field(default=None, ge=0, le=10000)
    viewport_height: int | None = Field(default=None, ge=0, le=10000)


class AiKnowledgeCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    component_id: int | None = None
    project_id: int | None = None
    title: str
    content: str
    tags: str | None = None
    source_type: str = "ai"
    confidence: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ComponentAiOut(BaseModel):
    component: ComponentOut
    knowledge_cards: list[AiKnowledgeCardOut] = []


class AiRefreshRequest(BaseModel):
    scope: str = "full"
    force: bool = True


class ComponentAiAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    use_web_search: bool = False


class ComponentAiAskOut(BaseModel):
    answer: str
    confidence: str = "medium"
    evidence: list[str] = []
    risks: list[str] = []
    needs_datasheet_check: bool = True
    sources: list[dict] = []


class AiTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_type: str
    target_type: str
    target_id: int
    status: str
    input_hash: str | None = None
    result_json: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    next_attempt_at: datetime | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AiTaskSummary(BaseModel):
    pending: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    stale: int = 0
    missing_components: int = 0
    current_component: str | None = None
    last_finished_at: datetime | None = None
    running: bool = False
    paused: bool = True


class ComponentConsumeRequest(BaseModel):
    quantity: int = Field(default=1, ge=1)
    reason_type: Literal["consume", "loss"] = "consume"
    project_id: int | None = None
    remark: str | None = None
    lot_id: str | None = None
    source_type: str | None = None
    source_reference: str | None = None
    location: str | None = None
    unit_cost: float | None = None


class EquipmentOccupancyRequest(BaseModel):
    action: Literal["occupy", "release"]
    quantity: int = Field(default=1, ge=1)
    remark: str | None = Field(default=None, max_length=1000)


class InventoryLotCreate(BaseModel):
    quantity: int = Field(default=1, ge=1)
    source_type: str = Field(default="manual", max_length=40)
    source_reference: str | None = Field(default=None, max_length=160)
    location: str | None = Field(default=None, max_length=200)
    unit_cost: float | None = Field(default=None, ge=0)
    note: str | None = None


class InventoryLotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    component_id: int
    source_type: str = "manual"
    source_reference: str | None = None
    location: str | None = None
    initial_quantity: int = 0
    remaining_quantity: int = 0
    unit_cost: float | None = None
    status: str = "active"
    received_at: datetime | None = None
    created_at: datetime | None = None
    can_delete: bool = False
    delete_block_reason: str | None = None


class BomItemStatusRequest(BaseModel):
    status: str
    consume_stock: bool = False
    remark: str | None = None


class AiClassifyRequest(BaseModel):
    name: str
    model: str | None = None
    parameters: str | None = None


class AiExplainRequest(BaseModel):
    name: str
    model: str | None = None
    parameters: str | None = None
    package: str | None = None


class AiProjectPlanRequest(BaseModel):
    goal: str


class ProjectAiPlanRequest(BaseModel):
    goal: str
    force: bool = False


class ProjectAiConsultRequest(BaseModel):
    question: str
    force: bool = True


class ImageImportPreviewRow(ComponentBase):
    confidence: str | None = None
    evidence_text: str | None = None
    category_suggestion: str | None = None
    matched_component_id: int | None = None
    match_score: int = 0
    lcsc_search_url: str | None = None
    action: str = "skip"


class AiComponentSearchRequest(BaseModel):
    requirement: str
    limit: int = Field(default=20, ge=1, le=50)


class AiComponentInfoRequest(BaseModel):
    query: str
    known_specs: str | None = None
    web_search: str = "auto"


class AuthLoginRequest(BaseModel):
    username: str | None = None
    phone: str | None = None
    password: str


class AuthLoginResponse(BaseModel):
    token: str
    user: dict | None = None


class AuthRegisterRequest(BaseModel):
    phone: str
    password: str
    nickname: str | None = None


class AuthResetCodeRequest(BaseModel):
    phone: str


class AuthResetPasswordRequest(BaseModel):
    phone: str
    code: str
    new_password: str
