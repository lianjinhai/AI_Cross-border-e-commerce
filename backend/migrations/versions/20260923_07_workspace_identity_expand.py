"""workspace identity expand (Revision A)

只新增结构，不回填数据、不修改 users、不触碰业务表。
设计依据：docs/phase1_migration_abc_design.md 第 1 节。

幂等：所有 create_table 前先检查表是否已存在（应用层 create_all 可能已建表）。
"""
from alembic import op
import sqlalchemy as sa

revision = "20260923_07"
down_revision = "20260922_06"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _tables()

    if "workspace_profiles" not in existing:
        op.create_table(
            "workspace_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id"),
                      nullable=False, unique=True),
            sa.Column("name", sa.String(128), nullable=False, server_default=""),
            sa.Column("kind", sa.String(32), nullable=False, server_default="ORGANIZATION"),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_workspace_profiles_tenant_id", "workspace_profiles", ["tenant_id"])

    if "workspace_roles" not in existing:
        op.create_table(
            "workspace_roles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(32), nullable=False, unique=True),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("description", sa.String(256), nullable=False, server_default=""),
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.true()),
        )

    if "permissions" not in existing:
        op.create_table(
            "permissions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(64), nullable=False, unique=True),
            sa.Column("domain", sa.String(32), nullable=False),
            sa.Column("action", sa.String(16), nullable=False),
            sa.Column("description", sa.String(256), nullable=False, server_default=""),
        )

    if "role_permissions" not in existing:
        op.create_table(
            "role_permissions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("role_key", sa.String(32), sa.ForeignKey("workspace_roles.key"),
                      nullable=False),
            sa.Column("permission_key", sa.String(64), sa.ForeignKey("permissions.key"),
                      nullable=False),
            sa.UniqueConstraint("role_key", "permission_key", name="uq_role_permission"),
        )
        op.create_index("ix_role_permissions_role_key", "role_permissions", ["role_key"])
        op.create_index("ix_role_permissions_permission_key", "role_permissions",
                        ["permission_key"])

    if "workspace_memberships" not in existing:
        op.create_table(
            "workspace_memberships",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("workspace_id", sa.Integer(),
                      sa.ForeignKey("workspace_profiles.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("role_key", sa.String(32), sa.ForeignKey("workspace_roles.key"),
                      nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("source", sa.String(24), nullable=False,
                      server_default="LEGACY_BACKFILL"),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership"),
        )
        op.create_index("ix_workspace_memberships_user_status", "workspace_memberships",
                        ["user_id", "status"])
        op.create_index("ix_workspace_memberships_workspace_status", "workspace_memberships",
                        ["workspace_id", "status"])

    if "membership_data_scopes" not in existing:
        op.create_table(
            "membership_data_scopes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("membership_id", sa.Integer(),
                      sa.ForeignKey("workspace_memberships.id"), nullable=False),
            sa.Column("scope_type", sa.String(32), nullable=False,
                      server_default="WORKSPACE_ALL"),
            sa.Column("scope_ref", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_membership_data_scopes_membership_id", "membership_data_scopes",
                        ["membership_id"])


def downgrade() -> None:
    existing = _tables()
    for table in ("membership_data_scopes", "workspace_memberships",
                  "role_permissions", "permissions", "workspace_roles",
                  "workspace_profiles"):
        if table in existing:
            op.drop_table(table)
