#!/usr/bin/env bash
# R3-2B Round2 驱动脚本：单次前台运行，避免后台进程被回收。
# 隔离后端 8010（qa_r32.db）+ 前端 5191（代理到 8010）→ 真实浏览器复验 → 收尾 kill。
set -u
ROOT="/f/Desktop/个人文件/软件开发计划/AI-电商ERP"
EV="$ROOT/docs/evidence/R3-2-QA"
PY="C:/Users/74488/AppData/Local/Programs/Python/Python311/python.exe"

cd "$ROOT/backend" || exit 1
ERP_DB_URL="sqlite:///F:/Desktop/个人文件/软件开发计划/AI-电商ERP/backend/qa_r32.db" \
ERP_JWT_SECRET="qa-r32-secret-at-least-32-bytes-long" \
ERP_SYNC_WORKFLOW=1 \
ERP_SUPERADMIN_PASSWORD="qa-root-123456" \
ERP_ENV=development \
"$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8010 > "$EV/_round2_backend.log" 2>&1 &
BACK=$!

cd "$ROOT/frontend-v9" || exit 1
VITE_API_PROXY_TARGET="http://127.0.0.1:8010" CODEBUDDY_SAFE_DELETE_ENABLED=0 \
  ./node_modules/.bin/vite --port 5191 --host 127.0.0.1 > "$EV/_round2_frontend.log" 2>&1 &
FRONT=$!

# 就绪轮询（Node fetch 直连，不经代理）
node -e '
const wait = async () => {
  for (let i=0;i<360;i++){
    try {
      const a=await fetch("http://127.0.0.1:8010/api/health",{signal:AbortSignal.timeout(2000)});
      const b=await fetch("http://127.0.0.1:5191/",{signal:AbortSignal.timeout(2000)});
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
  node docs/evidence/R3-2-QA/browser-verify.mjs > "$EV/_round2_browser.log" 2>&1
  echo "browser_rc=$?"
fi

kill $BACK $FRONT 2>/dev/null
echo "done"
