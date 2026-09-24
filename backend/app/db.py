"""数据库引擎与会话。"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

url = config.settings.db_url
_IS_SQLITE = url.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 30} if _IS_SQLITE else {}
engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


if _IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        """每个连接建立时统一设置 SQLite 并发参数。

        为什么需要：
          - journal_mode=WAL：读不阻塞写、写不阻塞读。默认的 delete 模式下写事务
            持排他锁，本项目有 180+ 个同步路由 + 调度器线程 + 工作流线程并发写入，
            极易触发 "database is locked" 500。
          - busy_timeout=30000：锁等待 30 秒而不是立刻失败（默认 5 秒）。
          - synchronous=NORMAL：WAL 下的安全且高效的持久化级别。
          - foreign_keys=ON：SQLite 默认不强制外键，开启后才能真正约束租户引用。
        注意：这些是连接级设置，必须逐连接执行。
        """
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 依赖：请求级会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(engine)
    _migrate_sqlite()
    _encrypt_legacy_shop_credentials()


def _encrypt_legacy_shop_credentials():
    """一次性把旧库已有明文凭证原地升级为 enc:v1 密文。"""
    if engine.url.get_backend_name() != "sqlite":
        return  # 非 SQLite 由正式迁移脚本执行，避免跨方言原生 SQL。
    from .secure_types import encrypt_database_value
    with engine.begin() as conn:
        try:
            rows = conn.exec_driver_sql(
                "SELECT id, app_secret, access_token, refresh_token FROM shops").all()
        except Exception:
            return
        for row in rows:
            values = [encrypt_database_value(str(v or "")) for v in row[1:]]
            if values != [str(v or "") for v in row[1:]]:
                conn.exec_driver_sql(
                    "UPDATE shops SET app_secret=?, access_token=?, refresh_token=? WHERE id=?",
                    (*values, row[0]))


def _migrate_sqlite():
    """轻量迁移：create_all 不会给已有表补列，此处为旧库补新增列。"""
    if engine.url.get_backend_name() != "sqlite":
        return
    with engine.connect() as conn:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(knowledge_docs)")]
        if "embedding" not in cols:
            conn.exec_driver_sql("ALTER TABLE knowledge_docs ADD COLUMN embedding JSON")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(orders)")]
        if "tracking_no" not in cols:
            conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN tracking_no VARCHAR(64) DEFAULT ''")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(shops)")]
        if "role" not in cols:
            conn.exec_driver_sql("ALTER TABLE shops ADD COLUMN role VARCHAR(16) DEFAULT 'sales'")
        if "archived_at" not in cols:
            # 归档式软删除（见 routers/shops.py::delete_shop）；NULL = 正常可用。
            conn.exec_driver_sql("ALTER TABLE shops ADD COLUMN archived_at DATETIME")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(orders)")]
        if "source" not in cols:
            conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN source VARCHAR(16) DEFAULT 'seed'")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(market_trends)")]
        if "source" not in cols:
            # M5 趋势来源标记（api/csv/builtin）；存量行视为内置演示数据
            conn.exec_driver_sql(
                "ALTER TABLE market_trends ADD COLUMN source VARCHAR(16) DEFAULT 'builtin'")
        if "updated_at" not in cols:
            conn.exec_driver_sql("ALTER TABLE market_trends ADD COLUMN updated_at DATETIME")
        # 注意：必须重新读取 orders 的列。上面 `cols` 已被 market_trends 覆盖，
        # 沿用它会让本判断在「orders 已有 shop_id」时仍然为真，
        # 从而每次启动都执行 ALTER → "duplicate column name: shop_id"（服务无法启动）。
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(orders)")]
        if "shop_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN shop_id INTEGER")
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_shop_external "
                             "ON orders(tenant_id, shop_id, platform, external_no)")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(suppliers)")]
        if "settlement_days" not in cols:
            conn.exec_driver_sql("ALTER TABLE suppliers ADD COLUMN settlement_days INTEGER DEFAULT 30")
        if "supplier_type" not in cols:
            conn.exec_driver_sql("ALTER TABLE suppliers ADD COLUMN supplier_type VARCHAR(32) DEFAULT 'trader'")
        if "verification_status" not in cols:
            conn.exec_driver_sql("ALTER TABLE suppliers ADD COLUMN verification_status VARCHAR(24) DEFAULT 'verified'")
        if "capabilities" not in cols:
            conn.exec_driver_sql("ALTER TABLE suppliers ADD COLUMN capabilities JSON DEFAULT '[]'")
        if "certifications" not in cols:
            conn.exec_driver_sql("ALTER TABLE suppliers ADD COLUMN certifications JSON DEFAULT '[]'")
        if "source_kind" not in cols:
            conn.exec_driver_sql("ALTER TABLE suppliers ADD COLUMN source_kind VARCHAR(32) DEFAULT 'manual'")
        if "source_url" not in cols:
            conn.exec_driver_sql("ALTER TABLE suppliers ADD COLUMN source_url VARCHAR(1024) DEFAULT ''")
        if "source_checked_at" not in cols:
            conn.exec_driver_sql("ALTER TABLE suppliers ADD COLUMN source_checked_at DATETIME")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(purchase_orders)")]
        if "settlement_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE purchase_orders ADD COLUMN settlement_id INTEGER")
        if "sales_order_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE purchase_orders ADD COLUMN sales_order_id INTEGER")
        if "source_shop_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE purchase_orders ADD COLUMN source_shop_id INTEGER")
        if "idempotency_key" not in cols:
            conn.exec_driver_sql("ALTER TABLE purchase_orders ADD COLUMN idempotency_key VARCHAR(128)")
            conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_purchase_idempotency_key ON purchase_orders(idempotency_key)")
        if "platform_trade_no" not in cols:
            conn.exec_driver_sql("ALTER TABLE purchase_orders ADD COLUMN platform_trade_no VARCHAR(128) DEFAULT ''")
        if "purchase_type" not in cols:
            conn.exec_driver_sql("ALTER TABLE purchase_orders ADD COLUMN purchase_type VARCHAR(24) DEFAULT 'stock'")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(platform_publish_attempts)")]
        if "requested_by" not in cols:
            conn.exec_driver_sql("ALTER TABLE platform_publish_attempts ADD COLUMN requested_by INTEGER")
        if "request_payload" not in cols:
            conn.exec_driver_sql("ALTER TABLE platform_publish_attempts ADD COLUMN request_payload JSON DEFAULT '{}'")
        if "started_at" not in cols:
            conn.exec_driver_sql("ALTER TABLE platform_publish_attempts ADD COLUMN started_at DATETIME")
        if "finished_at" not in cols:
            conn.exec_driver_sql("ALTER TABLE platform_publish_attempts ADD COLUMN finished_at DATETIME")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(supplier_offers)")]
        if "currency" not in cols:
            conn.exec_driver_sql("ALTER TABLE supplier_offers ADD COLUMN currency VARCHAR(8) DEFAULT 'CNY'")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(forecast_snapshots)")]
        if "target_start" not in cols:
            conn.exec_driver_sql("ALTER TABLE forecast_snapshots ADD COLUMN target_start DATETIME")
        if "target_end" not in cols:
            conn.exec_driver_sql("ALTER TABLE forecast_snapshots ADD COLUMN target_end DATETIME")
        cols = [r[1] for r in conn.exec_driver_sql(
            "PRAGMA table_info(opportunity_supplier_matches)")]
        if "promoted_at" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE opportunity_supplier_matches ADD COLUMN promoted_at DATETIME")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(listings)")]
        if "model" not in cols:
            conn.exec_driver_sql("ALTER TABLE listings ADD COLUMN model VARCHAR(16) DEFAULT 'rule'")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(workflow_runs)")]
        if "worker_id" not in cols:
            conn.exec_driver_sql("ALTER TABLE workflow_runs ADD COLUMN worker_id VARCHAR(64) DEFAULT ''")
        if "lease_until" not in cols:
            conn.exec_driver_sql("ALTER TABLE workflow_runs ADD COLUMN lease_until DATETIME")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(workflow_steps)")]
        if "attempts" not in cols:
            conn.exec_driver_sql("ALTER TABLE workflow_steps ADD COLUMN attempts INTEGER DEFAULT 0")
        if "max_attempts" not in cols:
            conn.exec_driver_sql("ALTER TABLE workflow_steps ADD COLUMN max_attempts INTEGER DEFAULT 3")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(users)")]
        if "status" not in cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN status VARCHAR(16) DEFAULT 'active'")
        if "token_version" not in cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 0")
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(listings)")]
        if "created_by" not in cols:
            conn.exec_driver_sql("ALTER TABLE listings ADD COLUMN created_by INTEGER")
        if "last_edited_by" not in cols:
            conn.exec_driver_sql("ALTER TABLE listings ADD COLUMN last_edited_by INTEGER")
        conn.commit()
