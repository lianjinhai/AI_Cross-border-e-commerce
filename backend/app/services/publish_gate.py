"""上架合规闸门：发布前回答「这个商品能不能发布到这个平台」（只读）。

为什么需要独立成服务：`compliance_registry` 只回答「某目的国要求什么、证据齐不齐」，
但**发布链路真正要回答的是另一个问题**——这件商品、这个平台，现在能不能发。缺的那一环是
「目的国从哪来」：商品没写 `destination_country`、店铺没配站点时，系统要么默认放行
（等于把合规风险转嫁给运营），要么一刀切阻断（等于把合规债务变成可用性事故）。

本模块的立场（2026-10 确立）：
    1. **只读**，绝不改任何业务数据——它是闸门，不是规则编辑器；
    2. **目的国必须解析出来**，解析不出时明确告知「无法校验」，**不得静默通过**。
       沉默的绿灯比红灯更危险：运营只会照着绿灯上架；
    3. **两种模式，语义不同**（2026-10 返工后定稿）：
       - ``mode="enforce"``（发布链路的实际取值）：缺证据返回 ``gate_status="block"``，
         调用方**必须**真正拦截上架；
       - ``mode="warn"``（``evaluate()`` 的默认值，供只读试算/界面预览使用）：
         缺证据只返回 ``warn`` + 原因，**不阻断**。
       之所以留一个不阻断的默认值：给「手动试算 / 证据预览」这类**不产生上架
       行为**的场景用，避免它们把UI 查询变成硬失败。

调用方：
    - `action_publish.publish_facts()`（所有发布路径的唯一公共出口，enforce 模式，
      真实店铺 is_demo=0 时拦截；本地 shop=None 与 demo 店铺保留旁路）；
    - 各适配器 `publish_listing` 前的 `_enforce_publish_gate()`（阻断口径）。

分层：只依赖准入规则和国家归一化；不引用 Adapter 注册表，供 Action 与 Adapter 共用。
"""
import logging

from . import compliance_registry
from .duty import duty_country
from .regions import store_market

logger = logging.getLogger(__name__)

# enforce 对缺失资料、未知市场及检查故障均返回 block。
GATE_PASS = "pass"
GATE_WARN = "warn"
GATE_BLOCK = "block"

MODE_WARN = "warn"
MODE_ENFORCE = "enforce"


def _attr(product, key: str) -> str:
    """安全读取商品 attrs（商品可能是 ORM，也可能是测试桩对象）。"""
    return str((getattr(product, "attrs", None) or {}).get(key) or "").strip()


def resolve_destination(db, product, platform: str = "", shop=None) -> str:
    """店铺发布只采用店铺目标国家；无店铺的只读预览可读商品声明。"""
    if shop is not None:
        return store_market(getattr(shop, "market", "") or "")
    for key in ("destination_country", "target_country"):
        code = duty_country(_attr(product, key))
        if code:
            return code
    return ""


def _names(entries) -> list[str]:
    """把 check_evidence 的条目列表收敛成去重后的认证项名称列表（便于记日志）。"""
    return sorted({str(item.get("requirement") or "") for item in entries or []
                   if item.get("requirement")})


def evaluate(db, tenant_id, *, product, platform: str = "", shop=None,
             mode: str = MODE_WARN) -> dict:
    """评估某商品能否发布到某平台，返回只读结论（不抛异常、不改数据）。

    :param mode: ``warn``（只读预览）/ ``enforce``（真实发布，故障阻断）。
    :returns: 含 ``gate_status`` / ``destination_country`` / ``required`` /
        ``missing`` / ``expired`` / ``would_block`` / ``reasons`` / ``mode``。
    """
    country = resolve_destination(db, product, platform, shop)
    result = {
        "gate_status": GATE_PASS,
        "destination_country": country,
        "required": [],
        "missing": [],
        "expired": [],
        "would_block": [],
        "reasons": [],
        "mode": mode,
        "product_id": getattr(product, "id", None),
        "platform": platform or "",
        "shop_id": getattr(shop, "id", None),
    }
    if not country:
        # 目的国解析不出来 = 无法校验。绝不能因此判定为通过。
        result["gate_status"] = GATE_BLOCK if mode == MODE_ENFORCE else GATE_WARN
        result["reasons"].append("目标国家未配置或当前不支持，无法校验目的国准入")
        return result
    try:
        report = compliance_registry.check_evidence(db, tenant_id, product, country)
    except Exception as exc:  # noqa: BLE001 —— 故障必须阻断真实发布
        result["gate_status"] = GATE_BLOCK if mode == MODE_ENFORCE else GATE_WARN
        result["reasons"].append(f"目的国 {country} 准入校验失败，请稍后重试")
        logger.warning("publish_gate_evaluate_failed tenant=%s product=%s country=%s err=%s",
                       tenant_id, result["product_id"], country, exc)
        return result
    result["required"] = _names(report.get("required"))
    result["missing"] = _names(report.get("missing"))
    result["expired"] = _names(report.get("expired"))
    for item in report.get("expired") or []:
        result["reasons"].append(
            f"目的国 {country} 准入认证已过期：{item.get('requirement')}"
            f"（{item.get('valid_until')}）")
    for name in result["missing"]:
        result["reasons"].append(f"目的国 {country} 缺少准入认证：{name}")
    result["would_block"] = result["missing"] + result["expired"]
    if result["would_block"]:
        # enforce：调用方（publish_facts）据此真正拦截上架。
        # warn：只提示，调用方记日志后继续，不把合规债务变成可用性事故。
        result["gate_status"] = (GATE_BLOCK if mode == MODE_ENFORCE else GATE_WARN)
    elif report.get("required"):
        result["reasons"].append(
            f"目的国 {country} 准入要求已齐备：" + "、".join(result["required"]))
    return result


def log_warn(result: dict, *, channel: str) -> None:
    """记录非通过结论，是否阻断由明确 mode 决定。"""
    logger.warning(
        "publish_compliance_warn channel=%s product_id=%s platform=%s shop_id=%s "
        "country=%s missing=%s expired=%s reasons=%s",
        channel, result.get("product_id"), result.get("platform"),
        result.get("shop_id"), result.get("destination_country"),
        result.get("missing"), result.get("expired"), result.get("reasons"))
