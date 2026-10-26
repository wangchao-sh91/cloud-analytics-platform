from datetime import datetime
from ipaddress import ip_address
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["available", "in_use", "maintenance", "retired"]
Short = Annotated[str, Field(max_length=255)]
Summary = Annotated[str, Field(max_length=2000)]


class Fields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1, max_length=255)]
    service_tag: Annotated[str, Field(min_length=1, max_length=64)]
    model: Annotated[str, Field(min_length=1, max_length=255)]
    management_ip: Short | None = None
    idrac_ip: Short | None = None
    lab: Short | None = None
    rack: Short | None = None
    rack_unit: Annotated[int, Field(gt=0, le=2147483647, strict=True)] | None = None
    cpu_summary: Summary | None = None
    memory_summary: Summary | None = None
    disk_summary: Summary | None = None
    owner: Short | None = None
    purpose: Summary | None = None
    notes: Annotated[str, Field(max_length=10000)] | None = None
    status: Status = "available"

    @field_validator("*", mode="before")
    @classmethod
    def normalize(cls, value, info):
        if isinstance(value, str):
            value = value.strip()
            if info.field_name == "service_tag":
                value = value.upper()
            if not value and info.field_name not in {"name", "service_tag", "model", "status"}:
                return None
        return value

    @field_validator("management_ip", "idrac_ip")
    @classmethod
    def valid_ip(cls, value):
        if value is not None:
            try:
                ip_address(value)
            except ValueError:
                raise ValueError("Enter a valid IPv4 or IPv6 address") from None
        return value


class CreateServer(Fields):
    pass


class PatchServer(Fields):
    # Missing fields are excluded with exclude_unset; explicit null is rejected
    # for required fields by the inherited non-null type.
    name: Annotated[str, Field(min_length=1, max_length=255)] = Field(default=None)  # type: ignore
    service_tag: Annotated[str, Field(min_length=1, max_length=64)] = Field(default=None)  # type: ignore
    model: Annotated[str, Field(min_length=1, max_length=255)] = Field(default=None)  # type: ignore


class ServerOut(Fields):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    created_at: datetime
    updated_at: datetime


class ServerPage(BaseModel):
    items: list[ServerOut]
    total: int
    page: int
    page_size: int
