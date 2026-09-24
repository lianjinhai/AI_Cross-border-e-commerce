# ---- 前端构建 ----
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --no-fund --no-audit; \
    else npm install --no-fund --no-audit; fi
COPY frontend/ ./ 
RUN npm run build

# ---- 后端运行 ----
# 命名该阶段：可用 `docker build --target runtime .` 在前端不可构建时独立验证后端镜像
FROM python:3.11-slim AS runtime
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ . 
COPY --from=frontend-build /build/dist /app/frontend/dist
# 启动脚本负责先跑迁移再拉起服务（见 docker-entrypoint.sh）
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && useradd --create-home --uid 10001 erp \
    && mkdir -p /data && chown -R erp:erp /data /app

ENV ERP_DB_URL=sqlite:////data/erp.db
ENV ERP_HOST=0.0.0.0
VOLUME ["/data"]
EXPOSE 8000
USER erp

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
