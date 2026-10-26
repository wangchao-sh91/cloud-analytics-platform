"""Initial physical server inventory."""
from alembic import op
import sqlalchemy as sa

revision = "001_inventory"
down_revision = None


def upgrade():
    op.create_table(
        "physical_servers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("service_tag", sa.String(64), nullable=False, unique=True),
        sa.Column("model", sa.String(255), nullable=False),
        *[sa.Column(n, sa.String(255)) for n in ["management_ip", "idrac_ip", "lab", "rack", "owner"]],
        sa.Column("rack_unit", sa.Integer()),
        *[sa.Column(n, sa.String(2000)) for n in ["cpu_summary", "memory_summary", "disk_summary", "purpose"]],
        sa.Column("notes", sa.String(10000)),
        sa.Column("status", sa.String(32), nullable=False, server_default="available"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('available','in_use','maintenance','retired')", name="valid_status"),
        sa.CheckConstraint("rack_unit > 0", name="positive_rack_unit"),
    )


def downgrade():
    op.drop_table("physical_servers")
