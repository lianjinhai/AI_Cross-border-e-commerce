"""D61 Expand 1a：发布兼容状态、平台事实与核验状态分离。

只增加列。历史 published/succeeded 不推断为 ACTIVE/VERIFIED。
店铺派生关系与店铺上下文在后续增量处理；本修订不改变历史归属。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261011_22"
down_revision = "20261001_21"
branch_labels = None
depends_on = None

COMMON = ("platform_status", "verification_status", "external_object_type")
EXTRA = ("raw_status", "received_at", "mapping_version")
TABLES = {"listings": COMMON, "platform_publish_attempts": COMMON + EXTRA}


def _snapshot(table, ignored):
    inspector = sa.inspect(op.get_bind())
    columns = tuple((c["name"], str(c["type"]), c["nullable"])
                    for c in inspector.get_columns(table) if c["name"] not in ignored)
    count = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
    indexes = sorted(inspector.get_indexes(table), key=lambda value: value["name"])
    foreign_keys = sorted(inspector.get_foreign_keys(table), key=lambda value: value["constrained_columns"])
    return columns, indexes, foreign_keys, count


def upgrade():
    for table, names in TABLES.items():
        before = _snapshot(table, names)
        present = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
        for name in names:
            if name in present:
                continue  # 测试/新安装 create_all 已建列；不覆盖已有事实。
            if name == "received_at":
                column = sa.Column(name, sa.DateTime(), nullable=True)
            else:
                size = {"external_object_type": 32, "raw_status": 256, "mapping_version": 64}.get(name, 24)
                column = sa.Column(name, sa.String(size), nullable=False,
                                   server_default="UNKNOWN" if name in COMMON else "")
            op.add_column(table, column)
        assert _snapshot(table, names) == before, f"{table} 历史结构或行数变化"


def downgrade():
    # 有新事实时拒绝有损降级；不能为恢复旧代码而删除平台证据。
    for table, names in TABLES.items():
        conditions = [f"{name} <> 'UNKNOWN'" for name in COMMON]
        if table == "platform_publish_attempts":
            conditions += ["raw_status <> ''", "mapping_version <> ''", "received_at IS NOT NULL"]
        count = op.get_bind().execute(sa.text(
            f"SELECT count(*) FROM {table} WHERE " + " OR ".join(conditions))).scalar_one()
        if count:
            raise RuntimeError(f"{table} 已存在新平台事实，拒绝有损降级；请备份并 forward-fix")
    for table, names in reversed(tuple(TABLES.items())):
        before = _snapshot(table, names)
        with op.batch_alter_table(table) as batch:
            for name in reversed(names):
                batch.drop_column(name)
        after = _snapshot(table, names)
        assert after == before, f"{table} 降级改变历史结构或行数: {before!r} -> {after!r}"
