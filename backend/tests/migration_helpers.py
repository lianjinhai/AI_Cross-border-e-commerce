"""测试迁移元数据；只读脚本目录，不创建数据库连接。"""

from pathlib import Path

from alembic.script import ScriptDirectory


def code_head():
    head = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "migrations")).get_current_head()
    assert head, "迁移目录必须存在唯一 head"
    return head
