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

    # 前端构建产物目录（存在时由后端托管）
    frontend_dist: str = os.path.join(os.path.dirname(_BACKEND_DIR), "frontend", "dist")

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
