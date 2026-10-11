"""D61 Expand 1b：店铺目标市场与经营上下文；不推测历史值。"""

import sqlalchemy as sa
from alembic import op

revision = "20261011_23"
down_revision = "20261011_22"
branch_labels = None
depends_on = None

FIELDS = {"market": 8, "store_type": 64, "account_type": 64,
          "business_mode": 64, "fulfillment_mode": 32}


def _legacy_snapshot():
    inspector = sa.inspect(op.get_bind())
    added = set(FIELDS) | {"capability_revision", "capability_evidence"}
    columns = [(c["name"], str(c["type"]), c["nullable"])
               for c in inspector.get_columns("shops") if c["name"] not in added]
    indexes = sorted(inspector.get_indexes("shops"), key=lambda value: value["name"])
    keys = sorted(inspector.get_foreign_keys("shops"), key=lambda value: value["constrained_columns"])
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM shops")).scalar_one()
    return columns, indexes, keys, inspector.get_pk_constraint("shops"), count


def upgrade():
    before = _legacy_snapshot()
    present = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("shops")}
    for name, size in FIELDS.items():
        if name not in present:
            op.add_column("shops", sa.Column(name, sa.String(size), nullable=False, server_default=""))
    if "capability_revision" not in present:
        op.add_column("shops", sa.Column("capability_revision", sa.Integer(), nullable=False, server_default="0"))
    if "capability_evidence" not in present:
        op.add_column("shops", sa.Column("capability_evidence", sa.JSON(), nullable=False, server_default="{}"))
    assert _legacy_snapshot() == before, "店铺增量改变历史结构、索引、约束或行数"


def downgrade():
    before = _legacy_snapshot()
    # 先逐行检查，JSON 由 SQLAlchemy 解析，避免 SQLite/PG 的 JSON 比较差异。
    table = sa.Table("shops", sa.MetaData(), autoload_with=op.get_bind())
    columns = [table.c[name] for name in (*FIELDS, "capability_revision", "capability_evidence")]
    for row in op.get_bind().execute(sa.select(*columns)).mappings():
        if any(row[name] for name in FIELDS) or row["capability_revision"] or row["capability_evidence"]:
            raise RuntimeError("店铺已有市场或能力配置，拒绝有损降级；请备份并 forward-fix")
    with op.batch_alter_table("shops") as batch:
        batch.drop_column("capability_evidence")
        batch.drop_column("capability_revision")
        for name in reversed(FIELDS):
            batch.drop_column(name)
    assert _legacy_snapshot() == before, "店铺降级改变历史结构、索引、约束或行数"
