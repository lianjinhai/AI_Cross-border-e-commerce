#!/usr/bin/env bash
# R3-2 定向验证：筛选上下文闭环（隔离后端 8010 + dev 5191）。
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
"$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8010 > "$EV/_loop_backend.log" 2>&1 &
BACK=$!

cd "$ROOT/frontend-v9" || exit 1
VITE_API_PROXY_TARGET="http://127.0.0.1:8010" CODEBUDDY_SAFE_DELETE_ENABLED=0 \
  ./node_modules/.bin/vite --port 5191 --host 127.0.0.1 > "$EV/_loop_frontend.log" 2>&1 &
FRONT=$!

node -e '
const wait = async () => {
  for (let i=0;i<120;i++){
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
  node docs/evidence/R3-2-QA/browser-verify-loop.mjs > "$EV/_loop_browser.log" 2>&1
  echo "loop_rc=$?"
fi

kill $BACK $FRONT 2>/dev/null
echo "done"
