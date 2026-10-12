"""局部工作流事务辅助；不改全站 SQLite 连接与旧事务语义。"""


def ensure_write_transaction(db):
    connection = db.connection()
    if connection.dialect.name == "sqlite":
        # sqlite3 legacy transaction control 不为 SELECT/保存点自动 BEGIN。
        # 必须先有真实外层事务，否则 RELEASE SAVEPOINT 会早于调用方 commit 生效。
        driver = connection.connection.driver_connection
        if not driver.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
