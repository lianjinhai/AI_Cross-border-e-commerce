#!/usr/bin/env bash
# B1 独立验证驱动（真实浏览器 · Chrome CDP）
# 隔离基座：后端 8011（qa_b1.db，每次从 qa_r33_base.db 还原）+ dev 5193（代理到 8011）
# 用法：bash docs/evidence/V9-1-B1/_b1_run.sh
set -u
ROOT="/f/Desktop/个人文件/软件开发计划/AI-电商ERP"
EV="$ROOT/docs/evidence/V9-1-B1"
PY="C:/Users/74488/AppData/Local/Programs/Python/Python311/python.exe"
BASE="$ROOT/backend/qa_r33_base.db"
DB="$ROOT/backend/qa_b1.db"

# 基线快照（与 R3-3 同种子库：含 qa_owner/qa_newbie/商品25·26/店铺3·4）
if [ ! -f "$BASE" ]; then
  echo "base_missing"; exit 1
fi
# 必须同时清掉 -wal/-shm：只覆盖主库文件时，SQLite 启动会回放旧 WAL，
# 上一轮创建的流程会「复活」→ 验证结果不可重复。
rm -f "$DB" "$DB-wal" "$DB-shm"
cp "$BASE" "$DB" || { echo "db_reset_failed"; exit 1; }

# 端口占用预检（避免连到残留进程，得到假结果）
node -e '
const net = require("node:net");
const probe = (port) => new Promise((res) => {
  const s = net.connect({ host: "127.0.0.1", port }, () => { s.destroy(); res(true) });
  s.on("error", () => res(false));
  s.setTimeout(1500, () => { s.destroy(); res(false) });
});
(async () => {
  const busy = [];
  for (const p of [8011, 5193]) if (await probe(p)) busy.push(p);
  if (busy.length) { console.log("PORT_BUSY:" + busy.join(",")); process.exit(1) }
  console.log("PORTS_FREE");
})();
'
if [ $? -ne 0 ]; then echo "abort: ports busy"; exit 1; fi

cd "$ROOT/backend" || exit 1
ERP_DB_URL="sqlite:///F:/Desktop/个人文件/软件开发计划/AI-电商ERP/backend/qa_b1.db" \
ERP_JWT_SECRET="qa-r32-secret-at-least-32-bytes-long" \
ERP_SYNC_WORKFLOW=1 \
ERP_SUPERADMIN_PASSWORD="qa-root-123456" \
ERP_ENV=development \
"$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8011 > "$EV/_b1_backend.log" 2>&1 &
BACK=$!

cd "$ROOT/frontend-v9" || exit 1
VITE_API_PROXY_TARGET="http://127.0.0.1:8011" CODEBUDDY_SAFE_DELETE_ENABLED=0 \
  ./node_modules/.bin/vite --port 5193 --host 127.0.0.1 > "$EV/_b1_frontend.log" 2>&1 &
FRONT=$!

node -e '
const wait = async () => {
  for (let i=0;i<360;i++){
    try {
      const a=await fetch("http://127.0.0.1:8011/api/health",{signal:AbortSignal.timeout(2000)});
      const b=await fetch("http://127.0.0.1:5193/",{signal:AbortSignal.timeout(2000)});
      if(a.ok&&b.ok){console.log("READY");process.exit(0)}
    } catch{}
    await new Promise(r=>setTimeout(r,1000));
  }
  console.log("NOT_READY");process.exit(1);
};
wait();
'
RC=$?
echo "readiness_rc=$RC"

if [ "$RC" = "0" ]; then
  cd "$ROOT" || exit 1
  timeout 240 node "docs/evidence/V9-1-B1/browser-verify-b1.mjs" > "$EV/_b1_browser.log" 2>&1
  echo "browser_rc=$?"
  tail -80 "$EV/_b1_browser.log"
fi

kill $BACK $FRONT 2>/dev/null
sleep 1
echo "done"
