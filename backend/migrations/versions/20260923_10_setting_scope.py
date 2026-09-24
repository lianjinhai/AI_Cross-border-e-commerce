"""setting scope isolation (Revision D)

把租户级配置（platform_fees / fx / rules）从全局 settings 表隔离到 tenant_settings，
保留 settings 作为平台级配置与平台默认值。

设计依据：docs/phase1_setting_scope_design.md

背景（已实测确认的跨租户写入漏洞）：
  settings 表主键只有 key，没有租户维度；PUT /api/ai/settings 由任意租户 admin
  即可调用，改动 platform_fees / fx / rules 会直接影响**其他所有租户**的定价与
  利润计算。本 revision 做 Expand + Backfill；代码侧改为「租户级 → 平台级 →
  代码默认」三级回退。

幂等：create_table 前先检查；回填用 INSERT OR IGNORE（依赖 unique(tenant_id,key)）。
不修改、不删除 settings 表任何数据（原行保留为平台默认值）。
"""
import sqlalchemy as sa
from alembic import op

revision = "20260923_10"
down_revision = "20260923_09"
branch_labels = None
depends_on = None

# 需要租户级隔离的 key（平台级 key 如 llm / 1688_api 不进此表）
_TENANT_SCOPED_KEYS = ("platform_fees", "fx", "rules")


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    existing = _tables()

    if "tenant_settings" not in existing:
        op.create_table(
            "tenant_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(),
                      sa.ForeignKey("tenants.id"), nullable=False, index=True),
            sa.Column("key", sa.String(64), nullable=False),
            sa.Column("value", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("tenant_id", "key", name="uq_tenant_setting"),
        )

    # ---- 回填：把全局默认复制给每个真实租户（不移动、不删除原行）----
    keys = ",".join("'%s'" % k for k in _TENANT_SCOPED_KEYS)
    tenants = [r[0] for r in bind.execute(
        sa.text("SELECT id FROM tenants WHERE id <> 0 ORDER BY id"))]
    settings = bind.execute(sa.text(
        "SELECT key, value FROM settings WHERE key IN (%s)" % keys)).fetchall()

    inserted = 0
    for tenant_id in tenants:
        for key, value in settings:
            result = bind.execute(sa.text(
                "INSERT OR IGNORE INTO tenant_settings (tenant_id, key, value, updated_at) "
                "VALUES (:t, :k, :v, CURRENT_TIMESTAMP)"),
                {"t": tenant_id, "k": key, "v": value})
            inserted += result.rowcount or 0

    print("[Revision D] tenants=%d settings=%d backfilled=%d"
          % (len(tenants), len(settings), inserted))


def downgrade() -> None:
    existing = _tables()
    if "tenant_settings" in existing:
        op.drop_table("tenant_settings")
