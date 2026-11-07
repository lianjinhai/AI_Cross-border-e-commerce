"""M2-E 标签：新建 label_packages（标签包版本历史，只增不改）。

修订 20261107_33（down_revision = 20261107_32）。纯新增表 + 三条索引，不改任何既有表
结构，存量库升级后行为不变（无标签包时 ``verified_artifact.LABEL_PACKAGE`` 仍为
UNKNOWN，``LABEL_PREPARATION`` 保持未完成——与升级前完全一致）。

为什么新建表：``LABEL_PREPARATION`` 的完成条件 ``verified_artifact: LABEL_PACKAGE``
此前**没有任何生产者**，条件永远求值为 UNKNOWN。要么伪造一个布尔值，要么永远卡住。
本表给出第三条路：标签包作为**真实存在的工件**落库，含依据快照与指纹，依据一变即失效。
详见 ``app/services/label_packages.py`` 与 D67。

downgrade 对称删表；有标签包时拒绝有损降级（已印出的标签是合规审计凭据，
不能因为回滚迁移就消失）。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261107_33"
down_revision = "20261107_32"
branch_labels = None
depends_on = None

_TABLE = "label_packages"
_INDEXES = ("ix_label_packages_product_created", "ix_label_packages_destination_country",
            "ix_label_packages_shop_id", "ix_label_packages_run_id",
            "ix_label_packages_product_id", "ix_label_packages_tenant_id")


def upgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table(_TABLE):
        return  # 幂等：create_all 先行建过表时直接跳过
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(),
                  sa.ForeignKey("tenants.id", name="fk_label_packages_tenant_id_tenants"),
                  nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("shop_id", sa.Integer(),
                  sa.ForeignKey("shops.id", name="fk_label_packages_shop_id_shops"),
                  nullable=False),
        sa.Column("run_id", sa.Integer(),
                  sa.ForeignKey("workflow_runs.id", name="fk_label_packages_run_id_workflow_runs"),
                  nullable=True),
        sa.Column("step_code", sa.String(48), nullable=False, server_default=""),
        sa.Column("destination_country", sa.String(8), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("action", sa.String(16), nullable=False, server_default="GENERATE"),
        sa.Column("content", sa.JSON(), nullable=True),
        sa.Column("content_digest", sa.String(64), nullable=False, server_default=""),
        sa.Column("basis", sa.JSON(), nullable=True),
        sa.Column("basis_fingerprint", sa.String(64), nullable=False, server_default=""),
        sa.Column("open_items", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "product_id", "shop_id", "destination_country", "version",
                            name="uq_label_packages_tenant_product_shop_country_version"),
    )
    op.create_index("ix_label_packages_tenant_id", _TABLE, ["tenant_id"])
    op.create_index("ix_label_packages_product_id", _TABLE, ["product_id"])
    op.create_index("ix_label_packages_shop_id", _TABLE, ["shop_id"])
    op.create_index("ix_label_packages_run_id", _TABLE, ["run_id"])
    op.create_index("ix_label_packages_destination_country", _TABLE, ["destination_country"])
    op.create_index("ix_label_packages_product_created", _TABLE, ["tenant_id", "product_id", "id"])


def downgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    rows = bind.execute(sa.text("SELECT count(*) FROM %s" % _TABLE)).scalar_one()
    if rows:
        raise RuntimeError(
            "%s 已有 %s 条标签包历史，拒绝有损降级；请先备份并 forward-fix" % (_TABLE, rows))
    for name in _INDEXES:
        op.drop_index(name, table_name=_TABLE)
    op.drop_table(_TABLE)
