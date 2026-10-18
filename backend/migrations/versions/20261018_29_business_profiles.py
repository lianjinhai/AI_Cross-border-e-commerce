"""D63 经营画像服务端持久化：business_profiles 表 + 部分唯一索引（共享行约束）。

修订 20261018_29（down_revision = 20261012_28）。仅新增表与索引，不影响既有表。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "20261018_29"
down_revision = "20261012_28"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if "business_profiles" not in tables:
        op.create_table(
            "business_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(),
                      sa.ForeignKey("tenants.id",
                                    name="fk_business_profiles_tenant_id_tenants"),
                      index=True, nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=True),
            sa.Column("user_id", sa.Integer(),
                      sa.ForeignKey("users.id",
                                    name="fk_business_profiles_user_id_users"),
                      nullable=True),
            sa.Column("direction", sa.String(32), nullable=True),
            sa.Column("budget_amount", sa.Float(), nullable=True),
            sa.Column("budget_currency", sa.String(8), nullable=True),
            sa.Column("target_market", sa.String(64), nullable=True),
            sa.Column("risk", sa.String(16), nullable=True),
            sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tenant_id", "workspace_id", "user_id",
                                name="uq_business_profile_personal"),
            sa.Index("ix_business_profiles_tenant", "tenant_id"),
            sa.Index("ix_business_profiles_workspace", "workspace_id"),
        )
    # 部分唯一索引：同一 (tenant, workspace) 仅允许一份共享画像（user_id IS NULL）。
    # 无论表是否由 create_all 先行建出，都确保该索引存在（幂等、可重复执行）。
    op.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_business_profiles_shared "
        "ON business_profiles (tenant_id, workspace_id) WHERE user_id IS NULL"
    ))


def downgrade():
    bind = op.get_bind()
    if bind.execute(text("SELECT count(*) FROM business_profiles")).scalar_one():
        raise RuntimeError(
            "business_profiles 已有数据，拒绝有损降级；请备份数据并 forward-fix")
    op.execute(text("DROP INDEX IF EXISTS ix_business_profiles_shared"))
    op.drop_table("business_profiles")
