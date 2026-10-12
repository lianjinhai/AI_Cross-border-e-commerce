"""D61：Launch 权限目录与既有角色增量，不创建平台专属权限或工厂身份。"""

import sqlalchemy as sa
from alembic import op

revision = "20261012_27"
down_revision = "20261012_26"
branch_labels = None
depends_on = None

GRANTS = {"read": ("OWNER", "OPERATOR", "READ_ONLY", "COMPLIANCE"),
          "create": ("OWNER", "OPERATOR"), "manage": ("OWNER", "OPERATOR"),
          "price_review": ("OWNER", "OPERATOR"), "stock_prepare": ("OWNER", "OPERATOR"),
          "compliance_manage": ("OWNER", "OPERATOR", "COMPLIANCE"),
          "label_manage": ("OWNER", "OPERATOR"), "submit": ("OWNER", "OPERATOR")}


def upgrade():
    bind = op.get_bind()
    if not {"permissions", "role_permissions"} <= set(sa.inspect(bind).get_table_names()):
        raise RuntimeError("Launch 权限依赖现有权限目录，缺表不能跳过")
    permissions = {row[0] for row in bind.execute(sa.text("SELECT key FROM permissions"))}
    grants = set(bind.execute(sa.text("SELECT role_key,permission_key FROM role_permissions")).all())
    for action, roles in GRANTS.items():
        key = "launch:" + action
        if key not in permissions:
            bind.execute(sa.text("INSERT INTO permissions(key,domain,action,description) VALUES(:key,'launch',:action,:description)"),
                         {"key": key, "action": action, "description": "商品上线生命周期：" + action})
        for role in roles:
            if (role, key) not in grants:
                bind.execute(sa.text("INSERT INTO role_permissions(role_key,permission_key) VALUES(:role,:key)"),
                             {"role": role, "key": key})


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM workflow_runs WHERE flow_kind='PLATFORM_LAUNCH'")).scalar_one():
        raise RuntimeError("已有 Launch，拒绝撤销运行所需权限；请先备份并 forward-fix")
    for action in GRANTS:
        key = "launch:" + action
        bind.execute(sa.text("DELETE FROM role_permissions WHERE permission_key=:key"), {"key": key})
        bind.execute(sa.text("DELETE FROM permissions WHERE key=:key"), {"key": key})
