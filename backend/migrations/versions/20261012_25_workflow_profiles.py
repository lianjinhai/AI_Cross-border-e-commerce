"""D61 Expand 2b：复用 WorkflowTemplate 保存版本化 Profile。"""

import sqlalchemy as sa
from alembic import op

revision = "20261012_25"
down_revision = "20261012_24"
branch_labels = None
depends_on = None

TEXT_FIELDS = {"definition_status": (16, "DRAFT"), "environment": (16, "CONTRACT_TEST"),
               "verification_status": (32, "UNKNOWN"), "platform": (32, ""), "market": (8, ""),
               "store_type": (64, ""), "account_type": (64, ""), "business_mode": (64, ""),
               "fulfillment_mode": (32, ""), "definition_hash": (64, "")}
EXTRA = {"profile_key", "version", "schema_version", "category_scope", "status_mapping"}
TABLE = "workflow_templates"
INDEX = "uq_workflow_profile_version"


def _snapshot():
    inspector = sa.inspect(op.get_bind())
    columns = [(c["name"], str(c["type"]), c["nullable"])
               for c in inspector.get_columns(TABLE) if c["name"] not in set(TEXT_FIELDS) | EXTRA]
    indexes = sorted((i for i in inspector.get_indexes(TABLE) if i["name"] != INDEX), key=lambda i: i["name"])
    keys = sorted(inspector.get_foreign_keys(TABLE), key=lambda i: i["constrained_columns"])
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM workflow_templates")).scalar_one()
    return columns, indexes, keys, inspector.get_pk_constraint(TABLE), count


def upgrade():
    before = _snapshot()
    columns = [sa.Column(name, sa.String(size), nullable=False, server_default=default)
               for name, (size, default) in TEXT_FIELDS.items()]
    columns += [sa.Column("profile_key", sa.String(64), nullable=True),
                sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
                sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
                sa.Column("category_scope", sa.JSON(), nullable=False, server_default="[]"),
                sa.Column("status_mapping", sa.JSON(), nullable=False, server_default="{}")]
    present = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}
    for column in columns:
        if column.name not in present:
            op.add_column(TABLE, column)
    if INDEX not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(TABLE)}:
        op.create_index(INDEX, TABLE, ["tenant_id", "profile_key", "version"], unique=True)
    assert _snapshot() == before, "Profile 扩展改变历史列、索引、约束或行数"


def downgrade():
    before = _snapshot()
    table = sa.Table(TABLE, sa.MetaData(), autoload_with=op.get_bind())
    for row in op.get_bind().execute(sa.select(table)).mappings():
        if (row["flow_kind"] != "LEGACY_AUTOMATION" or row["profile_key"] is not None
                or row["version"] != 1 or row["schema_version"] != 1
                or row["category_scope"] or row["status_mapping"]
                or any(row[name] != default for name, (_, default) in TEXT_FIELDS.items())):
            raise RuntimeError("已有 Profile 定义，拒绝有损降级；请备份并 forward-fix")
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_index(INDEX)
        for name in sorted(set(TEXT_FIELDS) | EXTRA, reverse=True):
            batch.drop_column(name)
    assert _snapshot() == before, "Profile 降级改变历史结构或行数"
