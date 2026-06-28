from typing import Literal

from pydantic import BaseModel, Field


TeamMarkerColor = Literal[
    "#F97316",
    "#EF4444",
    "#EAB308",
    "#22C55E",
    "#14B8A6",
    "#3B82F6",
    "#8B5CF6",
    "#EC4899",
]


class ContestLibraryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    competition_type: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class ContestLibraryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    competition_type: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    status: str | None = None


class ContestComponentBase(BaseModel):
    cw_component_id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    model: str | None = Field(default=None, max_length=200)
    lcsc_number: str | None = Field(default=None, max_length=120)
    quantity: int = Field(default=0, ge=0)
    location: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    package: str | None = Field(default=None, max_length=120)
    parameters: str | None = Field(default=None, max_length=1000)
    datasheet_url: str | None = Field(default=None, max_length=1000)
    tags: str | None = Field(default=None, max_length=300)
    remark: str | None = Field(default=None, max_length=2000)


class ContestComponentCreate(ContestComponentBase):
    pass


class ContestComponentUpdate(BaseModel):
    location: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=80)
    tags: str | None = Field(default=None, max_length=300)
    remark: str | None = Field(default=None, max_length=2000)


class TeamComponentQuantityUpdate(BaseModel):
    quantity: int = Field(ge=0)
    remark: str | None = Field(default=None, max_length=500)


class TeamMarkerCreate(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    color: TeamMarkerColor = "#F97316"
    flagged: bool = False
    note: str | None = Field(default=None, max_length=1000)


class TeamMarkerUpdate(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=80)
    color: TeamMarkerColor | None = None
    flagged: bool | None = None
    note: str | None = Field(default=None, max_length=1000)


class ContestComponentBulkAdd(BaseModel):
    items: list[dict]


class ContestComponentLink(BaseModel):
    cw_component_id: int


class ContestComponentRebind(BaseModel):
    cw_component_id: int


class ContestPcbBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    pcb_version: str | None = Field(default=None, max_length=80)
    function_desc: str | None = Field(default=None, max_length=2000)
    main_chip: str | None = Field(default=None, max_length=160)
    voltage: str | None = Field(default=None, max_length=80)
    interface_type: str | None = Field(default=None, max_length=160)
    suitable_task: str | None = Field(default=None, max_length=300)
    quantity: int = Field(default=1, ge=0)
    location: str | None = Field(default=None, max_length=200)
    status: str = "待确认"
    repository_url: str | None = Field(default=None, max_length=500)
    schematic_url: str | None = Field(default=None, max_length=500)
    datasheet_url: str | None = Field(default=None, max_length=500)
    remark: str | None = Field(default=None, max_length=2000)


class ContestPcbCreate(ContestPcbBase):
    pass


class ContestPcbUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    pcb_version: str | None = Field(default=None, max_length=80)
    function_desc: str | None = Field(default=None, max_length=2000)
    main_chip: str | None = Field(default=None, max_length=160)
    voltage: str | None = Field(default=None, max_length=80)
    interface_type: str | None = Field(default=None, max_length=160)
    suitable_task: str | None = Field(default=None, max_length=300)
    quantity: int | None = Field(default=None, ge=0)
    location: str | None = Field(default=None, max_length=200)
    status: str | None = None
    repository_url: str | None = Field(default=None, max_length=500)
    schematic_url: str | None = Field(default=None, max_length=500)
    datasheet_url: str | None = Field(default=None, max_length=500)
    remark: str | None = Field(default=None, max_length=2000)


class ContestAiRequest(BaseModel):
    query_type: str
    prompt: str = Field(min_length=1, max_length=2000)
    force: bool = False
