from pydantic import BaseModel, Field


class SupplierPartCreate(BaseModel):
    component_id: int
    supplier: str = Field(min_length=1, max_length=120)
    supplier_part_number: str = Field(min_length=1, max_length=160)
    purchase_url: str | None = None
    currency: str = "CNY"
    unit_price: float | None = Field(default=None, ge=0)
    is_preferred: bool = False


class EdaLibraryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    description: str | None = None


class EdaLibraryVersionCreate(BaseModel):
    version: str = Field(min_length=1, max_length=80)
    change_note: str | None = None
    compatible_with_previous: bool = True


class EdaObjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    description: str | None = None


class EdaAssetPublish(BaseModel):
    upload_token: str
    library_version_id: str | None = None
    version_label: str | None = Field(default=None, max_length=80)
    source_url: str | None = None
    source_license: str | None = Field(default=None, max_length=200)
    verification_status: str = "raw"
    entity_type: str | None = None
    entity_id: str | None = None
    relation_type: str = "attachment"


class EdaRemoteDownload(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class EdaBindingCreate(BaseModel):
    component_id: int
    library_version_id: str | None = None
    symbol_id: str | None = None
    footprint_id: str | None = None
    datasheet_asset_id: str | None = None
    model_asset_id: str | None = None
    source: str | None = Field(default=None, max_length=160)
    note: str | None = None
    is_primary: bool = True


class EdaQuickBindingCreate(BaseModel):
    component_id: int
    library_version_id: str | None = None
    symbol_name: str | None = Field(default=None, max_length=240)
    footprint_name: str | None = Field(default=None, max_length=240)
    datasheet_asset_id: str | None = None
    model_asset_id: str | None = None
    source: str | None = Field(default=None, max_length=160)
    note: str | None = None


class EdaSyncDraftCreate(BaseModel):
    base_version_id: str
    version: str | None = Field(default=None, max_length=80)
    change_note: str | None = None


class EdaVerificationCreate(BaseModel):
    status: str
    checklist: dict = Field(default_factory=dict)
    evidence_asset_id: str | None = None
    note: str | None = None


class EdaSyncTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    expires_in_days: int | None = Field(default=365, ge=1, le=3650)


class PurchaseOrderCreate(BaseModel):
    project_id: int | None = None
    order_number: str | None = Field(default=None, max_length=160)
    platform: str | None = Field(default=None, max_length=120)
    status: str = "planned"
    currency: str = "CNY"
    note: str | None = None


class PurchaseLineCreate(BaseModel):
    component_id: int | None = None
    supplier_part_id: str | None = None
    receiver_user_id: int | None = None
    description: str = Field(min_length=1, max_length=300)
    ordered_quantity: int = Field(ge=1)
    unit_price: float | None = Field(default=None, ge=0)
    purchase_url: str | None = None
    note: str | None = None


class PurchaseReceiptCreate(BaseModel):
    quantity: int = Field(ge=1)
    location: str | None = Field(default=None, max_length=200)
    note: str | None = None


class RiskUpdate(BaseModel):
    status: str


class RiskIssueCreate(BaseModel):
    component_id: int | None = None
    project_id: int | None = None
    risk_type: str = Field(pattern="^(footprint_issue|purchase_issue)$")
    severity: str = Field(default="warning", pattern="^(danger|warning|info)$")
    title: str = Field(min_length=1, max_length=240)
    detail: str | None = None
