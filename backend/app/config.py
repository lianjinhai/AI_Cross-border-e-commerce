"""全局配置：环境变量优先，未设置时使用开发默认值。"""
import os

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 开发环境默认 JWT 密钥：32 字节（满足 RFC 7518 对 HS256 的最小建议长度，
# 避免 PyJWT 的 InsecureKeyLengthWarning）。生产环境强制显式配置且不得等于此值。
#
# ⚠️ 变更此常量会同时影响 secure_types.py 派生出的开发期凭据加密密钥——
# 若库中已有 `enc:v1:` 密文，改常量会导致旧密文无法解密（需重新录入凭证）。
DEV_JWT_SECRET = "dev-secret-change-me-in-prod-32bytes"


def _load_dotenv() -> None:
    """加载仓库根或 backend/ 下的 .env（存在时才加载，缺失不报错）。

    为什么需要：.env.example 列出了全部运维变量，但此前没有任何代码读取 .env，
    运维按示例配置后变量静默不生效——这是最危险的一类配置缺陷。

    规则：已存在的真实环境变量优先，.env 不覆盖（override=False），
    因此容器/CI 显式注入的变量永远胜出。
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return  # 未安装 python-dotenv 时保持纯环境变量模式
    load_dotenv(os.path.join(os.path.dirname(_BACKEND_DIR), ".env"), override=False)
    load_dotenv(os.path.join(_BACKEND_DIR, ".env"), override=False)


_load_dotenv()


def _env_flag(name: str) -> bool:
    """严格布尔环境变量：仅显式 `1` 为真。

    为什么不用 `bool(os.getenv(name))`：非空即真会把 `ERP_X=0`
    （运维本意是「关闭」）当成「开启」，门禁形同虚设（DEBT-23 实测发现）。
    """
    return os.getenv(name, "").strip() == "1"


class Settings:
    app_name = "AI-Commerce ERP"
    # 数据库：默认 SQLite（开发），可用 ERP_DB_URL 切换 MySQL 等
    db_url: str = os.getenv(
        "ERP_DB_URL",
        "sqlite:///" + os.path.join(_BACKEND_DIR, "erp.db"),
    )
    # 开发默认值：32 字节（满足 RFC 7518 对 HS256 的最小建议长度），
    # 避免开发/测试期触发 PyJWT 的 InsecureKeyLengthWarning。
    # 生产环境仍强制要求显式配置且不得使用该默认值（见 validate_production_settings）。
    jwt_secret: str = os.getenv("ERP_JWT_SECRET", DEV_JWT_SECRET)
    jwt_expire_minutes: int = int(os.getenv("ERP_JWT_EXPIRE_MINUTES", "720"))
    environment: str = os.getenv("ERP_ENV", "development").strip().lower()
    cors_origins: list[str] = [x.strip() for x in os.getenv(
        "ERP_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if x.strip()]

    # LLM 兜底配置（实际运行时优先读取数据库 Setting 表中的 llm 配置）
    llm_api_key: str = os.getenv("ERP_LLM_API_KEY", "")
    llm_base_url: str = os.getenv("ERP_LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    llm_model: str = os.getenv("ERP_LLM_MODEL", "glm-4-flash")
    llm_model_small: str = os.getenv("ERP_LLM_MODEL_SMALL", "glm-4-flash")
    llm_embedding_model: str = os.getenv("ERP_LLM_EMBEDDING_MODEL", "embedding-3")
    llm_timeout: int = int(os.getenv("ERP_LLM_TIMEOUT", "45"))

    # 工作流调试模式：1 = 同步执行（测试用），0 = 后台线程执行
    sync_workflow: bool = os.getenv("ERP_SYNC_WORKFLOW", "0") == "1"

    # 前端构建产物目录（存在时由后端托管）。
    # 默认仍指向旧 frontend/dist（可回退）；设置 ERP_FRONTEND_DIST 可切换到
    # frontend-v9/dist（V9 接管正式入口）。这是「用户看不到新版界面」的根因——
    # 此前该路径写死为 frontend/dist，V9 构建产物从未被任何入口部署。
    frontend_dist: str = os.getenv(
        "ERP_FRONTEND_DIST",
        os.path.join(os.path.dirname(_BACKEND_DIR), "frontend", "dist"),
    )

    # 构建版本标识：暴露给 /api/build-info，便于判断用户究竟访问哪一套前端。
    # ERP_BUILD_ID / ERP_BUILD_SHA / ERP_BUILD_TIME 由发布链路（CI/entrypoint）注入。
    build_id: str = os.getenv("ERP_BUILD_ID", "")
    build_sha: str = os.getenv("ERP_BUILD_SHA", "")
    build_time: str = os.getenv("ERP_BUILD_TIME", "")

    # 反向代理信任开关（见 Caddyfile / docker-compose.tls.yml）
    #
    # 启用后应用采信 X-Forwarded-For / -Proto，使访问日志与 request.url 反映
    # 真实客户端与协议，而不是代理容器地址与 http。
    #
    # **默认关闭**：若应用可被绕过代理直连，任何人都能伪造 X-Forwarded-For
    # 污染审计信息（实测：uvicorn 在 `FORWARDED_ALLOW_IPS=*` 下无条件采信，
    # 直连即可把客户端 IP 伪装成任意值）。
    # 只有确认「外部无法直连后端」时才开启——docker-compose.tls.yml 已用
    # `!reset` 清空 8000 端口映射来保证这一点。
    trust_proxy_headers: bool = _env_flag("ERP_TRUST_PROXY_HEADERS")

    # 可信代理来源（IP / CIDR，逗号分隔）。
    #
    # 只有来自这些地址的转发头才被采信——这是「信任开关」之外的第二道闸：
    # 即便开了 trust_proxy_headers，来自非可信地址的 X-Forwarded-For 依然被忽略。
    # 默认 `127.0.0.1`（与 uvicorn 默认一致，即「本机反代」）。
    # Docker 部署需覆盖为容器网段（见 docker-compose.tls.yml）。
    trusted_proxy_hosts: list[str] = [x.strip() for x in os.getenv(
        "ERP_TRUSTED_PROXY_HOSTS", "127.0.0.1").split(",") if x.strip()]

    host: str = os.getenv("ERP_HOST", "127.0.0.1")
    port: int = int(os.getenv("ERP_PORT", "8000"))


settings = Settings()


def validate_production_settings() -> None:
    """生产环境拒绝带着开发密钥或默认管理员口令启动。"""
    if settings.environment != "production":
        return
    if len(settings.jwt_secret.encode("utf-8")) < 32 or settings.jwt_secret == DEV_JWT_SECRET:
        raise RuntimeError("生产环境必须配置至少 32 字节的 ERP_JWT_SECRET")
    if os.getenv("ERP_ADMIN_PASSWORD", "") in ("", "admin123"):
        raise RuntimeError("生产环境必须配置非默认 ERP_ADMIN_PASSWORD")
    if not os.getenv("ERP_CREDENTIAL_KEY", ""):
        raise RuntimeError("生产环境必须配置独立 ERP_CREDENTIAL_KEY")
    if os.getenv("ERP_RULES_URL", "") and not os.getenv("ERP_RULES_SIGNING_KEY", ""):
        raise RuntimeError("生产环境启用 ERP_RULES_URL 时必须配置 ERP_RULES_SIGNING_KEY")
    if not settings.cors_origins or "*" in settings.cors_origins:
        raise RuntimeError("生产环境 ERP_CORS_ORIGINS 必须是明确域名白名单")
    # 生产环境必须明确表态：要么在 TLS 代理之后（采信转发头），
    # 要么由外部设施负责 TLS。未表态时拒绝启动，而不是静默以 http 对外服务。
    #
    # 严格比对 `== "1"`：写成 `ERP_TLS_TERMINATED_ELSEWHERE=0`
    # （本意是「关闭」）不得被当成「已声明」而放行（DEBT-23 实测发现）。
    if not settings.trust_proxy_headers and not _env_flag("ERP_TLS_TERMINATED_ELSEWHERE"):
        raise RuntimeError(
            "生产环境必须明确 TLS 终止位置：置于反向代理后请设置 ERP_TRUST_PROXY_HEADERS=1"
            "（参考 Caddyfile / docker-compose.tls.yml）；"
            "若 TLS 由外部设施终止，请设置 ERP_TLS_TERMINATED_ELSEWHERE=1")
    # 公网回调地址必须是 https：平台 OAuth 回跳与前端跳转都依赖它，
    # 留 http 会让浏览器/平台判定为不安全连接（混合内容），授权链路直接失败。
    if settings.trust_proxy_headers and not settings.trusted_proxy_hosts:
        raise RuntimeError("生产环境启用 ERP_TRUST_PROXY_HEADERS 时必须配置 ERP_TRUSTED_PROXY_HOSTS")
    public_base = os.getenv("ERP_PUBLIC_BASE_URL", "").strip()
    if public_base and not public_base.startswith("https://"):
        raise RuntimeError(
            f"生产环境 ERP_PUBLIC_BASE_URL 必须是 https（当前：{public_base}）")
