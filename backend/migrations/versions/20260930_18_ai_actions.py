"""新增 AI Action 提案与审批状态表（D47）。

此迁移只建空表，不回填、不执行任何业务动作；downgrade 仅删本迁移创建的表。
"""

import sqlalchemy as sa
from alembic import op

revision = "20260930_18"
down_revision = "20260927_17"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("ai_actions"):
        return  # 测试库先由 create_all 建表时，Alembic 重放保持幂等
    op.create_table(
        "ai_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey(
            "tenants.id", name="fk_ai_actions_tenant_id_tenants"), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("agent_type", sa.String(64), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("expected_impact", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("required_permission", sa.String(64), nullable=False),
        sa.Column("execution_mode", sa.String(24), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("executed_by", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
    )
    for column in ("tenant_id", "workspace_id", "action_type", "target_id", "status"):
        op.create_index(f"ix_ai_actions_{column}", "ai_actions", [column])


def downgrade():
    if not sa.inspect(op.get_bind()).has_table("ai_actions"):
        return
    for column in ("status", "target_id", "action_type", "workspace_id", "tenant_id"):
        op.drop_index(f"ix_ai_actions_{column}", table_name="ai_actions")
    op.drop_table("ai_actions")
