"""factory supply network and evidence chain"""
from alembic import op
import sqlalchemy as sa

revision = "20260922_02"
down_revision = "20260922_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {x["name"] for x in inspector.get_columns("suppliers")}
    definitions = {
        "supplier_type": sa.Column("supplier_type", sa.String(32), server_default="trader", nullable=True),
        "verification_status": sa.Column("verification_status", sa.String(24), server_default="verified", nullable=True),
        "capabilities": sa.Column("capabilities", sa.JSON(), nullable=True),
        "certifications": sa.Column("certifications", sa.JSON(), nullable=True),
        "source_kind": sa.Column("source_kind", sa.String(32), server_default="manual", nullable=True),
        "source_url": sa.Column("source_url", sa.String(1024), server_default="", nullable=True),
        "source_checked_at": sa.Column("source_checked_at", sa.DateTime(), nullable=True),
    }
    missing = [(name, column) for name, column in definitions.items() if name not in existing]
    indexes = {x["name"] for x in inspector.get_indexes("suppliers")}
    with op.batch_alter_table("suppliers") as batch:
        for _, column in missing:
            batch.add_column(column)
        if "uq_supplier_source" not in indexes:
            batch.create_index("uq_supplier_source", ["tenant_id", "name", "source_url"], unique=True)
    from app.db import Base
    from app import models  # noqa: F401
    for name in ("supplier_evidence", "supplier_portal_members",
                 "supplier_catalog_products", "opportunity_supplier_matches"):
        Base.metadata.tables[name].create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.drop_table("opportunity_supplier_matches")
    op.drop_table("supplier_catalog_products")
    op.drop_table("supplier_portal_members")
    op.drop_table("supplier_evidence")
    with op.batch_alter_table("suppliers") as batch:
        batch.drop_index("uq_supplier_source")
        for name in ("source_checked_at", "source_url", "source_kind", "certifications",
                     "capabilities", "verification_status", "supplier_type"):
            batch.drop_column(name)
