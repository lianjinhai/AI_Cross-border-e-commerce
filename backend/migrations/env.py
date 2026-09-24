"""Alembic 环境：始终读取 ERP_DB_URL，与应用运行数据库保持一致。"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import config as app_config
from app import models  # noqa: F401
from app.db import Base

cfg = context.config
cfg.set_main_option("sqlalchemy.url", app_config.settings.db_url.replace("%", "%%"))
if cfg.config_file_name:
    fileConfig(cfg.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=cfg.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(cfg.get_section(cfg.config_ini_section),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True, render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


run_migrations_offline() if context.is_offline_mode() else run_migrations_online()
