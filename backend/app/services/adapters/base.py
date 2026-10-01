"""BaseAdapter：平台适配器的统一契约与通用守卫。

子类只实现平台差异；发布三道关（规则包校验 / 必填字段 / 类目映射）与
平台级限流在基类内聚，避免各平台重复实现。
"""
import time

from . import catmap
from .contract import NormalizedOrder, PlatformError, PublishResult, TokenPair


class BaseAdapter:
    """统一契约。子类只实现平台差异。"""
    platform = ""
    label = ""
    docs = ""
    role = "sales"
    # 能力清单：明确声明该平台支持什么，UI 按此禁用不可用操作
    can_order_sync = False
    can_publish = False
    can_refresh = False
    can_listing_readiness = False
    # 发布必需的外部资源（如类目映射）
    publish_requires_category_mapping = False
    publish_required_system_fields: list[str] = []
    integration_status = "planned"  # ready/partial/planned/restricted
    markets: list[str] = []
    auth_model = ""
    limitations: list[str] = []

    def __init__(self, db, shop):
        self.db = db
        self.shop = shop

    # ---- 通用守卫 ----
    def _ensure_authorized(self):
        s = self.shop
        if s.status != "authorized":
            raise PlatformError(f"店铺未授权（当前 {s.status}），请先完成 OAuth 授权")
        if s.token_expire_at and s.token_expire_at and s.token_expire_at.year and \
                s.token_expire_at.strftime("%Y%m%d%H%M%S") < time.strftime("%Y%m%d%H%M%S"):
            raise PlatformError("access_token 已过期，请刷新或重新授权")

    def _limiter(self):
        """平台级调用节流（规则包 rate_limit_per_sec），防频控封店。"""
        from ..platform_rules import RateLimiter, get_active_rules

        rules = get_active_rules(self.db, self.platform)["rules"]
        return RateLimiter(rules.get("rate_limit_per_sec", 10))

    def _pre_publish_checks(self, listing, product) -> None:
        """发布三道关之一：平台规则包强制校验（违禁词/长度/禁售类目/图片要求）。"""
        from ..platform_rules import validate_against_rules

        violations = validate_against_rules(self.db, self.platform, listing, product)
        if violations:
            raise PlatformError("平台规则校验未通过（为保护店铺拒绝发布）：" + "；".join(violations))

    # ---- 授权 ----
    def authorize_url(self) -> str:
        raise PlatformError(f"{self.label} 授权未实现")

    def exchange_code(self, code: str) -> TokenPair:
        raise PlatformError(f"{self.label} token 交换未实现")

    def refresh(self) -> TokenPair:
        raise PlatformError(f"{self.label} 不支持 token 刷新，请重新授权")

    # ---- 业务 ----
    def fetch_orders(self, days: int = 7) -> list[NormalizedOrder]:
        raise PlatformError(f"{self.label} 拉单协议待接入")

    def missing_publish_requirements(self, listing, product) -> list[str]:
        """发布前置校验：返回缺失项中文清单（空=可发布）。"""
        missing = []
        if self.publish_requires_category_mapping:
            if not product.category:
                missing.append("商品类目为空，无法映射平台类目")
            elif not catmap.category_mapping_for(self.db, self.shop.tenant_id,
                                          self.platform, product.category):
                missing.append(f"缺少「{product.category} → {self.label} 类目ID」映射，"
                               "请到店铺授权页维护类目映射")
        # 系统必填字段：由适配器声明字段名，逐项在 product.attrs 中校验
        attrs = product.attrs or {}
        for required in self.publish_required_system_fields:
            value = attrs.get(required)
            if required == "images":
                if not [u for u in (product.images or []) if str(u).startswith("http")]:
                    missing.append("缺少可公网访问的商品图片（images）")
            elif required == "stock":
                if int(attrs.get("onhand") or 0) <= 0:
                    missing.append("可售库存 onhand 必须大于 0")
            elif required == "price":
                if float(attrs.get("sale_price") or 0) <= 0:
                    missing.append("缺少有效销售价 sale_price")
            elif value in (None, "", [], {}):
                missing.append(f"缺少必填字段 {required}")
        if not (listing.keywords or []):
            missing.append("Listing 缺少关键词")
        missing.extend(self._destination_access_issues(product))
        return missing

    def _destination_access_issues(self, product) -> list[str]:
        """目的国准入检查（P1-4）：默认**不阻断**，需租户显式开启。

        为什么默认关闭：既有商品与 Listing 都没有目的国与证据数据，若默认强制
        阻断，会让所有上架流程因"未录入证据"而失败——那是把合规债务转嫁成可用性
        事故。开启开关（tenant_settings.rules.destination_compliance_enforce=true）
        且商品声明了目的国后才参与阻断。目的国来源：product.attrs.destination_country
        （后续可由店铺站点覆盖）。
        """
        from .. import compliance_registry
        from ..costing import DEFAULT_RULES, setting_for

        attrs = product.attrs or {}
        country = (attrs.get("destination_country") or attrs.get("target_country") or "")
        if not country:
            return []
        rules = setting_for(self.db, self.shop.tenant_id, "rules", DEFAULT_RULES)
        if not rules.get("destination_compliance_enforce"):
            return []
        report = compliance_registry.check_evidence(self.db, self.shop.tenant_id,
                                                   product, country)
        issues = []
        for item in report.get("blocking", []):
            if "valid_until" in item:
                issues.append(f"目的国 {report['country']} 准入认证已过期："
                              f"{item['requirement']}（{item['valid_until']}）")
            else:
                issues.append(f"目的国 {report['country']} 缺少准入认证：{item['requirement']}")
        return issues

    def publish_listing(self, listing, product, *, resume=None, checkpoint=None) -> PublishResult:
        raise PlatformError(f"{self.label} 上架协议待接入")

    def listing_readiness(self, listing, product) -> dict:
        raise PlatformError(f"{self.label} 尚未接入真实上架预检")

    def submission_status(self, submission_id: str) -> dict:
        raise PlatformError(f"{self.label} 不支持异步提交状态查询")
