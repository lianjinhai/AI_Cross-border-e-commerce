"""为调度任务保存真实发起人和 Workspace；历史记录不自动绑定。"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_19"
down_revision = "20260930_18"
branch_labels = None
depends_on = None


def _facts():
    inspector = sa.inspect(op.get_bind())
    skip = {"requested_by", "workspace_id"}
    columns = {column["name"]: (str(column["type"]), column["nullable"], column["default"])
               for column in inspector.get_columns("schedules") if column["name"] not in skip}
    indexes = {(index["name"], tuple(index["column_names"]), index["unique"])
               for index in inspector.get_indexes("schedules")}
    foreign_keys = {(fk["name"], fk["referred_table"], tuple(fk["constrained_columns"]),
                     tuple(fk["referred_columns"])) for fk in inspector.get_foreign_keys("schedules")
                    if not skip.intersection(fk["constrained_columns"])}
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM schedules")).scalar_one()
    return columns, indexes, foreign_keys, count


def upgrade():
    before = _facts()
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("schedules")}
    constraints = {fk["name"] for fk in inspector.get_foreign_keys("schedules")}
    with op.batch_alter_table("schedules") as batch:
        if "requested_by" not in columns:
            batch.add_column(sa.Column("requested_by", sa.Integer(), nullable=True))
        if "workspace_id" not in columns:
            batch.add_column(sa.Column("workspace_id", sa.Integer(), nullable=True))
        if "fk_schedules_requested_by_users" not in constraints:
            batch.create_foreign_key("fk_schedules_requested_by_users", "users", ["requested_by"], ["id"])
        if "fk_schedules_workspace_id_tenants" not in constraints:
            batch.create_foreign_key("fk_schedules_workspace_id_tenants", "tenants", ["workspace_id"], ["id"])
    assert _facts() == before, "调度迁移改变了既有列、索引、外键或行数"


def downgrade():
    before = _facts()
    with op.batch_alter_table("schedules") as batch:
        batch.drop_constraint("fk_schedules_workspace_id_tenants", type_="foreignkey")
        batch.drop_constraint("fk_schedules_requested_by_users", type_="foreignkey")
        batch.drop_column("workspace_id")
        batch.drop_column("requested_by")
    assert _facts() == before, "调度回滚改变了既有列、索引、外键或行数"
