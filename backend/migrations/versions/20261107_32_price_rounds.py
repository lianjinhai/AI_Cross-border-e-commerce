"""M2-A 核价：新建 price_rounds（报价轮次，只增不改）。

修订 20261107_32（down_revision = 20261106_31）。纯新增表 + 两条索引，
不改任何既有表结构，存量库升级后行为不变（无轮次时条件仍为 UNKNOWN）。

为什么新建表而不是复用 ``pricing_records``：那张表是 PricingAgent 的成本拆解快照，
同一报价会被反复计算；核价要的是「报过几个价、谁批的、依据哪份成本」的**历史**，
混用会把「算过利润」当成「价格已核」。详见 ``app/services/pricing_rounds.py``。

downgrade 对称删表；有数据时拒绝有损降级（报价历史是审计凭据，不能悄悄丢掉）。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261107_32"
down_revision = "20261106_31"
branch_labels = None
depends_on = None

_TABLE = "price_rounds"


def upgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table(_TABLE):
        return  # 幂等：create_all 先行建过表时直接跳过
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", name="fk_price_rounds_tenant_id_tenants"),
                  nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("run_id", sa.Integer(),
                  sa.ForeignKey("workflow_runs.id", name="fk_price_rounds_run_id_workflow_runs"),
                  nullable=True),
        sa.Column("step_code", sa.String(48), nullable=False, server_default=""),
        sa.Column("round_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("action", sa.String(16), nullable=False, server_default="REPORT"),
        sa.Column("price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default=""),
        sa.Column("margin", sa.Float(), nullable=False, server_default="0"),
        sa.Column("min_margin", sa.Float(), nullable=False, server_default="0"),
        sa.Column("margin_ok", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost_snapshot", sa.JSON(), nullable=True),
        sa.Column("cost_fingerprint", sa.String(64), nullable=False, server_default=""),
        sa.Column("decision", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "product_id", "round_no",
                            name="uq_price_rounds_tenant_product_no"),
    )
    op.create_index("ix_price_rounds_tenant_id", _TABLE, ["tenant_id"])
    op.create_index("ix_price_rounds_product_id", _TABLE, ["product_id"])
    op.create_index("ix_price_rounds_run_id", _TABLE, ["run_id"])
    op.create_index("ix_price_rounds_product_created", _TABLE, ["tenant_id", "product_id", "id"])


def downgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    rows = bind.execute(sa.text("SELECT count(*) FROM %s" % _TABLE)).scalar_one()
    if rows:
        raise RuntimeError(
            "%s 已有 %s 条报价历史，拒绝有损降级；请先备份并 forward-fix" % (_TABLE, rows))
    for name in ("ix_price_rounds_product_created", "ix_price_rounds_run_id",
                 "ix_price_rounds_product_id", "ix_price_rounds_tenant_id"):
        op.drop_index(name, table_name=_TABLE)
    op.drop_table(_TABLE)
