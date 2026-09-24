#!/bin/sh
# 容器启动入口：先执行数据库迁移，成功后再拉起服务。
#
# 为什么必须跑迁移：应用内的 create_all 只能建"缺表"，不能改已存在的表结构，
# 也不记录版本。若容器不跑 alembic，生产库 schema 会随代码演进无声漂移
# （历史上就因此出现过 User.tenant_id 与迁移后 schema 不一致的问题）。
#
# 迁移失败必须阻断启动：宁可容器起不来，也不能让旧 schema 带着新代码对外服务。
set -e

if [ "${ERP_SKIP_MIGRATIONS:-0}" = "1" ]; then
    echo "[entrypoint] ERP_SKIP_MIGRATIONS=1，跳过数据库迁移"
else
    echo "[entrypoint] 执行数据库迁移：alembic upgrade head"
    alembic upgrade head
fi

echo "[entrypoint] 启动应用：$*"
exec "$@"
