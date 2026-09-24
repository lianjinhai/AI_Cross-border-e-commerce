"""安全迁移入口：备份 SQLite 后执行兼容迁移并升级 Alembic 版本。"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic import command
from alembic.config import Config

from app import config
from app.db import init_db


def main() -> None:
    url = config.settings.db_url
    if url.startswith("sqlite:///"):
        db_path = Path(url.removeprefix("sqlite:///")).resolve()
        if db_path.exists():
            backup = db_path.with_name(db_path.name + ".bak-" + datetime.now().strftime("%Y%m%d%H%M%S"))
            shutil.copy2(db_path, backup)
            print(f"SQLite 迁移前备份：{backup}")
    init_db()  # 旧库先执行非破坏兼容补列
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    command.upgrade(cfg, "head")
    print("数据库已升级到 Alembic head")


if __name__ == "__main__":
    main()
