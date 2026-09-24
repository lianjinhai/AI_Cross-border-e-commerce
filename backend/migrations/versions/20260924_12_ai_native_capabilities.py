"""AI 原生能力（M1 选品飞轮 / M3 主动巡检 / M6 决策解释）

新增 4 张表：
  product_performances  商品真实经营表现（M1，仅统计 api/import/manual 来源订单）
  ai_decisions          AI 决策依据链（M6，只增不删）
  alert_rules           巡检规则配置（M3，阈值可调）
  alert_events          巡检告警实例（M3，只告警不执行）

设计依据：docs/AI原生能力升级方案.md（含三轮专家论证与四条设计红线）。
幂等：建表前检查表是否已存在；不修改、不删除任何既有数据。
"""
import sqlalchemy as sa
from alembic import op

revision = "20260924_12"
down_revision = "20260923_11"
branch_labels = None
depends_on = None

_TABLES = ("product_performances", "ai_decisions", "alert_rules", "alert_events")


def _has_table(name: str) -> bool:
    return name in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    created = []

    if "product_performances" not in existing:
        op.create_table(
            "product_performances",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
            sa.Column("window_days", sa.Integer(), server_default="30"),
            sa.Column("units_sold", sa.Integer(), server_default="0"),
            sa.Column("revenue", sa.Float(), server_default="0"),
            sa.Column("profit", sa.Float(), server_default="0"),
            sa.Column("margin", sa.Float(), server_default="0"),
            sa.Column("refund_rate", sa.Float(), server_default="0"),
            sa.Column("sell_through", sa.Float(), server_default="0"),
            sa.Column("performance_score", sa.Float(), server_default="50"),
            sa.Column("computed_at", sa.DateTime()),
        )
        op.create_index("ix_product_performances_tenant_id", "product_performances", ["tenant_id"])
        op.create_index("ix_product_performances_product_id", "product_performances", ["product_id"])
        op.create_index("ix_product_performances_computed_at", "product_performances", ["computed_at"])
        created.append("product_performances")

    if "ai_decisions" not in existing:
        op.create_table(
            "ai_decisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("agent", sa.String(32), nullable=False),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("subject_type", sa.String(32), nullable=False),
            sa.Column("subject_id", sa.Integer(), server_default="0"),
            sa.Column("decision", sa.JSON()),
            sa.Column("evidence", sa.JSON()),
            sa.Column("model", sa.String(64), server_default="rule"),
            sa.Column("created_at", sa.DateTime()),
        )
        op.create_index("ix_ai_decisions_tenant_id", "ai_decisions", ["tenant_id"])
        op.create_index("ix_ai_decisions_subject_type", "ai_decisions", ["subject_type"])
        op.create_index("ix_ai_decisions_subject_id", "ai_decisions", ["subject_id"])
        op.create_index("ix_ai_decisions_created_at", "ai_decisions", ["created_at"])
        created.append("ai_decisions")

    if "alert_rules" not in existing:
        op.create_table(
            "alert_rules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("key", sa.String(64), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("level", sa.String(16), server_default="mid"),
            sa.Column("threshold", sa.JSON()),
            sa.Column("enabled", sa.Boolean(), server_default=sa.true()),
            sa.Column("description", sa.String(512), server_default=""),
            sa.Column("created_at", sa.DateTime()),
        )
        op.create_index("ix_alert_rules_tenant_id", "alert_rules", ["tenant_id"])
        op.create_index("ix_alert_rules_key", "alert_rules", ["key"])
        created.append("alert_rules")

    if "alert_events" not in existing:
        op.create_table(
            "alert_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("rule_key", sa.String(64), nullable=False),
            sa.Column("level", sa.String(16), server_default="mid"),
            sa.Column("subject_type", sa.String(32), server_default=""),
            sa.Column("subject_id", sa.Integer(), server_default="0"),
            sa.Column("title", sa.String(256), nullable=False),
            sa.Column("detail", sa.Text()),
            sa.Column("evidence", sa.JSON()),
            sa.Column("status", sa.String(16), server_default="open"),
            sa.Column("acked_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime()),
        )
        op.create_index("ix_alert_events_tenant_id", "alert_events", ["tenant_id"])
        op.create_index("ix_alert_events_rule_key", "alert_events", ["rule_key"])
        op.create_index("ix_alert_events_created_at", "alert_events", ["created_at"])
        created.append("alert_events")

    print(f"[Revision 12] 已创建表: {created or '无（均已存在）'}")


def downgrade() -> None:
    for name in reversed(_TABLES):
        if _has_table(name):
            op.drop_table(name)
            print(f"[Revision 12] 已删除表 {name}")
