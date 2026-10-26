from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now():
    return datetime.now(timezone.utc)


class Server(Base):
    __tablename__ = "physical_servers"
    __table_args__ = (
        CheckConstraint("status IN ('available','in_use','maintenance','retired')", name="valid_status"),
        CheckConstraint("rack_unit > 0", name="positive_rack_unit"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255))
    service_tag: Mapped[str] = mapped_column(String(64), unique=True)
    model: Mapped[str] = mapped_column(String(255))
    management_ip: Mapped[str | None] = mapped_column(String(255))
    idrac_ip: Mapped[str | None] = mapped_column(String(255))
    lab: Mapped[str | None] = mapped_column(String(255))
    rack: Mapped[str | None] = mapped_column(String(255))
    rack_unit: Mapped[int | None] = mapped_column(Integer)
    cpu_summary: Mapped[str | None] = mapped_column(String(2000))
    memory_summary: Mapped[str | None] = mapped_column(String(2000))
    disk_summary: Mapped[str | None] = mapped_column(String(2000))
    owner: Mapped[str | None] = mapped_column(String(255))
    purpose: Mapped[str | None] = mapped_column(String(2000))
    notes: Mapped[str | None] = mapped_column(String(10000))
    status: Mapped[str] = mapped_column(String(32), default="available", server_default="available")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
