"""D61 Expand 2a：隔离旧自动化与平台生命周期，不改变旧状态。"""

import sqlalchemy as sa
from alembic import op

revision = "20261012_24"
down_revision = "20261011_23"
branch_labels = None
depends_on = None

TABLES = ("workflow_templates", "workflow_runs")
LEGACY = "LEGACY_AUTOMATION"


def _snapshot():
    inspector = sa.inspect(op.get_bind())
    result = {}
    for table in TABLES:
        columns = [(c["name"], str(c["type"]), c["nullable"])
                   for c in inspector.get_columns(table) if c["name"] != "flow_kind"]
        indexes = sorted((i for i in inspector.get_indexes(table) if i["column_names"] != ["flow_kind"]),
                         key=lambda item: item["name"])
        keys = sorted(inspector.get_foreign_keys(table), key=lambda item: item["constrained_columns"])
        count = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        result[table] = columns, indexes, keys, inspector.get_pk_constraint(table), count
    return result


def upgrade():
    before = _snapshot()
    for table in TABLES:
        inspector = sa.inspect(op.get_bind())
        if "flow_kind" not in {c["name"] for c in inspector.get_columns(table)}:
            op.add_column(table, sa.Column("flow_kind", sa.String(32), nullable=False, server_default=LEGACY))
        index = f"ix_{table}_flow_kind"
        if index not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}:
            op.create_index(index, table, ["flow_kind"])
    assert _snapshot() == before, "流程类型扩展改变旧列、索引、约束或行数"


def downgrade():
    before = _snapshot()
    # 先检查全部表，再进行任何 DDL，不能丢失新流程的类型归属。
    for name in TABLES:
        table = sa.Table(name, sa.MetaData(), autoload_with=op.get_bind())
        if op.get_bind().execute(sa.select(sa.func.count()).select_from(table).where(
                table.c.flow_kind != LEGACY)).scalar_one():
            raise RuntimeError("已有非旧自动化流程，拒绝有损降级；请备份并 forward-fix")
    for table in reversed(TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_flow_kind")
            batch.drop_column("flow_kind")
    assert _snapshot() == before, "流程类型降级改变历史结构或行数"
