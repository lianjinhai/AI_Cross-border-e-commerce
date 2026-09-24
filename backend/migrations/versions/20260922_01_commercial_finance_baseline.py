"""commercial finance baseline

该基线对空库创建当前完整模型；已有库先继续由兼容迁移补列，再 stamp 本版本。
后续所有结构变化必须使用显式 Alembic revision。
"""
from alembic import op

revision = "20260922_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db import Base
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    # 基线禁止自动全库删除；生产回滚必须从备份恢复并使用后续补偿迁移。
    pass
