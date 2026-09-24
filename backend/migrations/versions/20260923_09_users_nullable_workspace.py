"""users tenant_id nullable and superadmin detach (Revision C)

高风险 revision：SQLite 下用 batch_alter_table 重建 users 表。
前置条件（必须在执行前确认）：
  1. Revision B 的 Membership 回填已通过全部断言；
  2. 已生成 Revision C 前的独立冷备；
  3. 预检器 P0 全通过（除本 revision 将修复的 users->tenants FK 违规）。

设计依据：docs/phase1_migration_abc_design.md 第 3 节。
"""
from alembic import op
import sqlalchemy as sa

revision = "20260923_09"
down_revision = "20260923_08"
branch_labels = None
depends_on = None


def _users_columns() -> dict[str, dict]:
    return {c["name"]: c for c in sa.inspect(op.get_bind()).get_columns("users")}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _users_columns()
    tenant_col = columns.get("tenant_id")
    if tenant_col is None:
        raise RuntimeError("users.tenant_id 不存在，数据库结构与预期不符")

    # SQLite 不支持直接改 nullable，必须 batch rebuild。
    # 保留全部列与数据，只改 tenant_id 的 nullable 属性。
    if not tenant_col.get("nullable", False):
        with op.batch_alter_table("users") as batch:
            batch.alter_column("tenant_id", existing_type=sa.Integer(), nullable=True)

    # 解除 superadmin 的 FK 违规：tenant_id=0 在 tenants 表中不存在
    bind.execute(sa.text(
        "UPDATE users SET tenant_id = NULL "
        "WHERE LOWER(role) = 'superadmin' AND tenant_id = 0"))

    _assert_revision_c(bind)


def _assert_revision_c(bind) -> None:
    def scalar(sql: str):
        return bind.execute(sa.text(sql)).scalar()

    # 全新空库（首次部署）没有用户，无需校验 superadmin 归属；
    # 但只要有用户，就必须满足「superadmin 为 NULL、非 superadmin 不为 NULL」。
    total_users = scalar("SELECT COUNT(*) FROM users")
    superadmins = scalar(
        "SELECT COUNT(*) FROM users WHERE LOWER(role) = 'superadmin'")
    if total_users == 0:
        return

    null_users = scalar("SELECT COUNT(*) FROM users WHERE tenant_id IS NULL")
    assert null_users == superadmins, (
        f"tenant_id 为 NULL 的用户应恰好等于 superadmin 数量（{superadmins}），"
        f"实际 {null_users}——非 superadmin 不得为 NULL")

    zero_users = scalar("SELECT COUNT(*) FROM users WHERE tenant_id = 0")
    assert zero_users == 0, f"仍有 {zero_users} 个用户的 tenant_id=0"

    if superadmins:
        superadmin_null = scalar(
            "SELECT COUNT(*) FROM users WHERE LOWER(role) = 'superadmin' "
            "AND tenant_id IS NULL")
        assert superadmin_null == superadmins, (
            f"superadmin 的 tenant_id 未全部置为 NULL（{superadmin_null}/{superadmins}）")

    dup = scalar("SELECT COUNT(*) FROM (SELECT username FROM users "
                 "GROUP BY username HAVING COUNT(*) > 1)")
    assert dup == 0, f"username 重复 {dup} 组"

    # Membership 关联不应受影响
    orphan_members = scalar(
        "SELECT COUNT(*) FROM workspace_memberships wm "
        "LEFT JOIN users u ON u.id = wm.user_id WHERE u.id IS NULL")
    assert orphan_members == 0, "Revision C 后出现 Membership 孤儿引用"


def downgrade() -> None:
    bind = op.get_bind()
    # 还原 superadmin 的 tenant_id=0，再把列改回 NOT NULL。
    # 注意：若已存在其他 tenant_id 为 NULL 的用户，本 downgrade 会失败——
    # 这是有意的安全设计，防止静默丢失身份信息。
    bind.execute(sa.text(
        "UPDATE users SET tenant_id = 0 "
        "WHERE LOWER(role) = 'superadmin' AND tenant_id IS NULL"))
    remaining = bind.execute(sa.text(
        "SELECT COUNT(*) FROM users WHERE tenant_id IS NULL")).scalar()
    if remaining:
        raise RuntimeError(
            f"仍有 {remaining} 个用户的 tenant_id 为 NULL，拒绝 downgrade；"
            "请先人工确认这些用户应归属哪个租户")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("tenant_id", existing_type=sa.Integer(), nullable=False)
