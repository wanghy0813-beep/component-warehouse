from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ProjectStatusTransitionCreate(BaseModel):
    status: str
    note: str | None = None
    clear_end_date: bool = False
    source: str = "web"


class ProjectCodeChangeCreate(BaseModel):
    project_code: str


class ProjectPcbVersionCreate(BaseModel):
    version_code: str | None = None
    status: str = "designing"
    change_summary: str | None = None
    copy_from_version_id: int | None = None


class ProjectPcbVersionUpdate(BaseModel):
    version_code: str | None = None
    status: str | None = None
    change_summary: str | None = None
    make_active: bool | None = None


class ProjectPcbVersionOut(BaseModel):
    id: int
    project_id: int
    sequence_number: int
    version_code: str
    status: str
    change_summary: str | None = None
    active: bool = False
    bom_item_count: int = 0
    board_count: int = 0
    solder_total: int = 0
    soldered_count: int = 0
    solder_progress: int = 0
    material_estimate: Decimal | None = None
    actual_material_cost: Decimal = Decimal("0")
    direct_expense: Decimal = Decimal("0")
    comprehensive_cost: Decimal = Decimal("0")
    unpriced_count: int = 0
    validated_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectExpenseCreate(BaseModel):
    pcb_version_id: int | None = None
    category: str
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    occurred_on: date | None = None
    vendor: str | None = Field(default=None, max_length=200)
    note: str | None = None
    attachment_asset_id: str | None = None


class ProjectExpenseUpdate(BaseModel):
    pcb_version_id: int | None = None
    category: str | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    occurred_on: date | None = None
    vendor: str | None = Field(default=None, max_length=200)
    note: str | None = None
    attachment_asset_id: str | None = None


class ProjectExpenseOut(BaseModel):
    id: str
    project_id: int
    pcb_version_id: int | None = None
    version_code: str | None = None
    category: str
    amount: Decimal
    currency: str = "CNY"
    occurred_on: date
    vendor: str | None = None
    note: str | None = None
    attachment_asset_id: str | None = None
    archived_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectCostSummaryOut(BaseModel):
    project_id: int
    project_code: str | None = None
    bom_unit_estimate: Decimal | None = None
    planned_material_estimate: Decimal | None = None
    actual_material_cost: Decimal = Decimal("0")
    direct_expense: Decimal = Decimal("0")
    comprehensive_cost: Decimal = Decimal("0")
    planned_purchase_amount: Decimal = Decimal("0")
    committed_purchase_amount: Decimal = Decimal("0")
    unpriced_bom_items: int = 0
    unpriced_material_events: int = 0
    top_cost_items: list[dict] = Field(default_factory=list)
    weekly_trend: list[dict] = Field(default_factory=list)
    versions: list[dict] = Field(default_factory=list)
