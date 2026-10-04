"""BaseAdapter：平台适配器的统一契约与通用守卫。

子类只实现平台差异；发布三道关（规则包校验 / 必填字段 / 类目映射）与
平台级限流在基类内聚，避免各平台重复实现。
"""
import logging
import time

from . import catmap
from .contract import NormalizedOrder, PlatformError, PublishResult, TokenPair

logger = logging.getLogger(__name__)


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
    can_advert = False                      # 广告 API 是否已接入（D60 骨架）
    advert_protocol_status = "planned"      # planned / protocol_ready_unverified / verified
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
        """发布前置校验：返回缺失项中文清单（空=可发布）。

        商品/Listing 一律用 ``getattr`` 取字段：本方法的调用方既有ORM 实体，
        也有只带部分字段的轻量对象（如部分适配器的自检桩）。直接 ``product.category``
        会让缺字段的对象抛 AttributeError——那会让**整个前置校验崩掉**，
        比「少报一项」严重得多：闸门一旦抛异常，发布路径就跟着失败。
        缺失字段与空值在本方法里等价，都按「缺失」记。
        """
        missing = []
        category = getattr(product, "category", "") or ""
        if self.publish_requires_category_mapping:
            if not category:
                missing.append("商品类目为空，无法映射平台类目")
            elif not catmap.category_mapping_for(self.db, self.shop.tenant_id,
                                          self.platform, category):
                missing.append(f"缺少「{category} → {self.label} 类目ID」映射，"
                               "请到店铺授权页维护类目映射")
        # 系统必填字段：由适配器声明字段名，逐项在 product.attrs 中校验
        attrs = getattr(product, "attrs", None) or {}
        for required in self.publish_required_system_fields:
            value = attrs.get(required)
            if required == "images":
                if not [u for u in (getattr(product, "images", None) or [])
                         if str(u).startswith("http")]:
                    missing.append("缺少可公网访问的商品图片（images）")
            elif required == "stock":
                if int(attrs.get("onhand") or 0) <= 0:
                    missing.append("可售库存 onhand 必须大于 0")
            elif required == "price":
                if float(attrs.get("sale_price") or 0) <= 0:
                    missing.append("缺少有效销售价 sale_price")
            elif value in (None, "", [], {}):
                missing.append(f"缺少必填字段 {required}")
        # 用 getattr 兜底：部分适配器的调用方（及测试桩）传入的 listing 未必带
        # keywords 字段，直接 listing.keywords 会抛 AttributeError 把合规检查
        # 变成不可用。缺失与空列表在这里等价，都记「缺少关键词」。
        if not (getattr(listing, "keywords", None) or []):
            missing.append("Listing 缺少关键词")
        # 目的国准入：**始终计算**（不再受开关影响），是否计入阻断由下面的
        # destination_compliance_enforce 决定。开关是「阻断策略」而非「是否检查」。
        issues = self._destination_access_issues(product)
        if issues and self._destination_compliance_enforced():
            missing.extend(issues)
        return missing

    def _destination_compliance_enforced(self) -> bool:
        """租户是否已开启「目的国准入**阻断**」（tenant_settings.rules）。

        开关语义在 2026-10 被重新定义：它过去同时控制「查不查」与「拦不拦」，
        于是变成一个永远没人打开的死开关——检查从未真正执行过。现在
        「查」是无条件的（见 ``_destination_access_issues``），本开关只决定
        「缺证据时是否让上架失败」。未开启时准入缺口只记日志
        （``services/publish_gate.py`` 统一落warn 日志），不阻断。
        """
        from ..costing import DEFAULT_RULES, setting_for

        rules = setting_for(self.db, self.shop.tenant_id, "rules", DEFAULT_RULES)
        return bool(rules.get("destination_compliance_enforce"))

    def _enforce_publish_gate(self, listing, product, *, channel: str) -> list[str]:
        """发布前的**法定准入**守卫：所有 can_publish=True 的适配器都必须调用。

        为什么放在基类而不是各平台各写一遍：2026-10 的验收发现，eBay 修好闸门后
        lazada / tiktok / walmart 三个同样 ``can_publish=True`` 的平台**一次都不
        咨询闸门**——四个平台四种行为，任何人凭直觉都判断不出哪个是安全的。
        把口径收敛到基类，才能保证「新增平台默认就有闸门」。

        **只管法定准入这一件事**：目的国强制认证（FCC / CE / PSE / UKCA / KC /
        UN38.3 等）缺失即无条件拦截，不受租户开关
        ``destination_compliance_enforce`` 影响——这类风险是法律与平台处罚，
        不允许租户用一个开关换��下架或封店。

        刻意**不**在这里代替平台侧字段校验（类目映射 / 必填字段 / 关键词）：
        那些是各平台自己的前置条件，TikTok 有 ``listing_readiness``、Shopee 有
        自己的必填表，各有各的判据。基类越权代管只会与平台逻辑打架。
        那些项仍由 ``missing_publish_requirements()`` 承担（受租户开关控制），
        由各平台按自身需要调用。

        与 ``publish_facts`` 的分工：那里按 is_demo 放行本地与 demo 旁路
        （不对外产生真实上架），这里是适配器侧的第二道防线——即便将来出现
        绕过 publish_facts 的新调用路径，缺认证商品也发不出去。

        :returns: 恒为 ``[]``；保留返回值是为了调用方可在错误上下文里追加提示。
        """
        blocking = list(dict.fromkeys(self._destination_access_issues(product)))
        if blocking:
            logger.warning("publish_gate_blocked channel=%s platform=%s product_id=%s blocking=%s",
                           channel, self.platform, getattr(product, "id", None), blocking)
            raise PlatformError(
                f"{self.label} 发布前置校验未通过（合规闸门）：" + "；".join(blocking))
        return []

    def _destination_access_issues(self, product) -> list[str]:
        """目的国准入问题清单（P1-4）：**无条件计算**，只读不阻断。

        2026-10 移除了这里的开关判断。原实现「开关默认关闭 → 直接 return []」，
        加上 ``product.attrs.destination_country`` 为空也直接返回，
        等于这条合规检查在真实链路里几乎从不执行——上架美国站的充电器
        因FCC 漏词返回 required=[]，系统给出「无缺失、可上架」的绿灯。
        沉默的绿灯比红灯危险：运营只会照绿灯上架。

        因此现在无条件解析目的国并核验证据；「是否阻断」由调用方
        （``_destination_compliance_enforced``）决定，本批为 warn 语义。
        """
        from .. import compliance_registry

        attrs = product.attrs or {}
        country = (attrs.get("destination_country") or attrs.get("target_country") or "")
        if not country:
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

    # ---- 广告（D60 骨架：未接外部 API，只留契约与能力开关）----
    def create_ad_campaign(self, *, product_id: int, daily_budget: float,
                           currency: str = "USD", target_country: str = "",
                           keywords: list[str] | None = None) -> dict:
        """创建广告活动骨架。真实平台广告 API 需外部商家账号与 OAuth，
        本批禁止访问外网，故只留接口契约与 ``can_advert`` 开关——
        子类未覆盖时显式抛错，避免调用方误以为已投放。"""
        raise PlatformError(f"{self.label} 广告 API 未接入（advert_protocol_status="
                             f"{self.advert_protocol_status}），需外部商家账号授权后方可联调")

    def ad_campaign_status(self, campaign_id: str) -> dict:
        raise PlatformError(f"{self.label} 广告状态查询未接入")
