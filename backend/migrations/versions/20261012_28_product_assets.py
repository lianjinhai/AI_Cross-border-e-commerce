"""D61 Expand 3a：版本化商品素材及权利来源，旧图片不自动转为有权素材。"""

import sqlalchemy as sa
from alembic import op

revision = "20261012_28"
down_revision = "20261012_27"
branch_labels = None
depends_on = None


def upgrade():
    if "product_assets" in sa.inspect(op.get_bind()).get_table_names():
        return
    columns = [sa.Column("id", sa.Integer(), primary_key=True),
               sa.Column("workspace_id", sa.Integer(), nullable=False),
               sa.Column("version", sa.Integer(), nullable=False)]
    for name, target, nullable in (("tenant_id", "tenants", False), ("product_id", "products", False),
                                   ("parent_asset_id", "product_assets", True), ("created_by", "users", False)):
        columns.append(sa.Column(name, sa.Integer(), sa.ForeignKey(target + ".id",
                       name=f"fk_product_assets_{name}_{target}"), nullable=nullable))
    for name, size in (("asset_key", 128), ("asset_type", 32), ("uri", 2048), ("content_hash", 64),
                       ("rights_status", 32), ("source", 256), ("rights_evidence_ref", 2048),
                       ("market", 8), ("platform", 32), ("verification_status", 24)):
        columns.append(sa.Column(name, sa.String(size), nullable=False))
    columns += [sa.Column("valid_from", sa.DateTime(), nullable=True),
                sa.Column("valid_until", sa.DateTime(), nullable=True),
                sa.Column("manifest", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False)]
    op.create_table("product_assets", *columns,
                    sa.UniqueConstraint("tenant_id", "product_id", "asset_key", "version", name="uq_product_asset_version"),
                    sa.CheckConstraint("version > 0", name="ck_product_asset_version"))
    op.create_index("ix_product_assets_tenant_id", "product_assets", ["tenant_id"])
    op.create_index("ix_product_asset_usage", "product_assets", ["tenant_id", "product_id", "market", "platform", "asset_type"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM product_assets")).scalar_one():
        raise RuntimeError("已有素材版本或权利记录，拒绝有损降级；请备份并 forward-fix")
    op.drop_table("product_assets")
