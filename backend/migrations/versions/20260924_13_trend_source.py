"""M5 真实趋势接入：market_trends 增加 source / updated_at

source 如实标记趋势数据出处（api / csv / builtin），前端据此区分真实数据与
内置演示词池——红线 3「演示数据不进飞轮」在趋势域的延伸。

设计依据：docs/AI原生能力升级方案.md（M5）。
幂等：加列前检查列是否已存在；不修改、不删除任何既有数据（存量行默认 builtin）。
"""
import sqlalchemy as sa
from alembic import op

revision = "20260924_13"
down_revision = "20260924_12"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _index_names(table: str) -> set[str]:
    bind = op.get_bind()
    return {i["name"] for i in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    if "market_trends" not in set(sa.inspect(op.get_bind()).get_table_names()):
        print("[Revision 13] market_trends 表不存在，跳过")
        return
    cols = _columns("market_trends")
    if "source" not in cols:
        op.add_column("market_trends",
                      sa.Column("source", sa.String(16), server_default="builtin"))
        print("[Revision 13] market_trends.source 已添加（存量行标记为 builtin）")
    if "updated_at" not in cols:
        op.add_column("market_trends", sa.Column("updated_at", sa.DateTime()))
        print("[Revision 13] market_trends.updated_at 已添加")
    # 索引创建必须**独立于**列存在性判断：应用层 `db.py::_migrate_sqlite()`
    # 会在启动时自动补列，导致「列已存在、索引缺失」的部分漂移状态。
    # 若把 create_index 放在 `if "source" not in cols` 内，这种库上索引永远不会
    # 被创建，而账本却推进到本 revision——与 P1-03 记录的漂移根因完全同类。
    if "ix_market_trends_source" not in _index_names("market_trends"):
        op.create_index("ix_market_trends_source", "market_trends", ["source"])
        print("[Revision 13] ix_market_trends_source 已创建")


def downgrade() -> None:
    if "market_trends" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    cols = _columns("market_trends")
    if "updated_at" in cols:
        op.drop_column("market_trends", "updated_at")
    if "source" in cols:
        op.drop_index("ix_market_trends_source", table_name="market_trends")
        op.drop_column("market_trends", "source")
