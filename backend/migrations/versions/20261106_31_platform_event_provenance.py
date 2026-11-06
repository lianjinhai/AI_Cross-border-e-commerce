"""P0-2 平台状态摄入：platform_publish_attempts 增加外部事件来源留痕字段。

修订 20261106_31（down_revision = 20261019_30）。仅新增 4 个可空/有默认值的列，
不改既有列、不重建表、不影响存量行。

依据 `docs/PLATFORM_WORKFLOW_STATE_MODEL.md` §5：
「每次外部事件保留 raw_status、source、source_time、received_time、external_reference、
external_object_type、mapping_version、source_revision」。
其中 raw_status / received_at / external_object_type / mapping_version 已存在，
本次补齐 source / source_time / external_reference / source_revision。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261106_31"
down_revision = "20261019_30"
branch_labels = None
depends_on = None

_TABLE = "platform_publish_attempts"

# (列名, 类型, 服务端默认值)；source_revision 可空，用于「首事件无序号」的场景。
_COLUMNS = (
    ("source", sa.String(32), ""),
    ("source_time", sa.DateTime(), None),
    ("external_reference", sa.String(128), ""),
    ("source_revision", sa.Integer(), None),
)


def _existing_columns(bind):
    return {column["name"] for column in sa.inspect(bind).get_columns(_TABLE)}


def upgrade():
    bind = op.get_bind()
    existing = _existing_columns(bind)
    for name, type_, default in _COLUMNS:
        if name in existing:
            continue  # 幂等：可重复执行，也兼容 create_all 先行建出的列。
        op.add_column(_TABLE, sa.Column(
            name, type_, nullable=True,
            server_default=None if default is None else sa.text("'%s'" % default)))


def downgrade():
    bind = op.get_bind()
    existing = _existing_columns(bind)
    # 这四列是外部事件的可追溯凭据，删除即有损（无法再证明某条状态来自哪个回执）。
    # 有数据时拒绝降级，要求先备份并 forward-fix。
    for name, present in (("source_revision", "source_revision IS NOT NULL"),
                          ("external_reference", "external_reference != ''"),
                          ("source", "source != ''")):
        if name not in existing:
            continue
        rows = bind.execute(sa.text(
            "SELECT count(*) FROM %s WHERE %s" % (_TABLE, present))).scalar_one()
        if rows:
            raise RuntimeError(
                "%s.%s 已有外部事件留痕数据，拒绝有损降级；请备份后 forward-fix" % (_TABLE, name))
    for name, _, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column(_TABLE, name)
