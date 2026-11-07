"""阻断补齐入口（P0-4）：每个 blocked 项必须能回答「然后去哪」。

状态模型 §6 规定 blocker 必须含 `repair_action`，但此前全仓四处产生点都写死 `None`，
于是前端只能看到原因、不知道下一步——这就是「裸 409」。

设计三条硬约束：

1. **只指向真实存在的页面**。`path` 必须是前端已挂真实组件的路由；
   占位页（如素材中心 `StubPage`）不得作为补齐入口。
2. **能不能真的补齐要说清楚**。`connected=False` 表示该补齐动作背后的领域服务
   尚未接入（B03–B09），页面可看但无法在此完成——不造点不动的按钮冒充可用。
3. **永不返回 None**。没有专用入口时给 `UNAVAILABLE` + 兜底待办入口，
   让「没有入口」本身也是一条显式信息，而不是空白。
"""

from ..services import asset_upload

# 阻断码（状态模型 §6 固定枚举）→ 补齐入口。
# kind: ROUTE 跳页面 / ACTION 触发 Launch 动作 / UNAVAILABLE 能力未接入
_BY_CODE = {
    # 缺资料：能直接补的走商品资料确认；材料类走合规页（上传与核验服务未接入）
    "MISSING_DATA": {
        "label": "补充商品资料", "kind": "ACTION", "action": "COMPLETE_DATA",
        "path": "/app/products", "connected": True, "reason": "",
    },
    # 合规/素材/标签依据不足
    "COMPLIANCE_BLOCK": {
        "label": "查看合规材料要求", "kind": "ROUTE", "action": None,
        "path": "/app/compliance", "connected": False,
        "reason": "材料上传与核验服务未接入（B03–B09），合规页可查看要求但不能在此完成补齐",
    },
    # 标签依据不足（M2-E）：**不能再指去合规页**——那一页的「合规检测」卡片实际是
    # listing 评审队列，与目的国准入证据无关，用户跑一趟白跑。真正能补的地方是
    # 商品详情页的「目的国合规要求与证据」区块（读写 `GET/POST
    # /api/cross-border/products/{id}/compliance`），所以这里指商品详情。
    "LABEL_BASIS_MISSING": {
        "label": "去商品详情补目的国合规证据", "kind": "ROUTE", "action": None,
        "path": "/app/products", "connected": True, "reason": "",
    },
    # 低价：M2-A 起核价轮次接通，定价页能算出「多少钱才过门槛」并看轮次历史。
    # 边界：这里给的是**找到达标售价**的入口；提交报价轮次仍在 Launch 动作内
    # （REPORT_PRICE 需要 run + revision 上下文，定价页不持有流程状态）。
    "PRICE_UNACCEPTABLE": {
        "label": "去定价页测算达标售价", "kind": "ROUTE", "action": None,
        "path": "/app/pricing", "connected": True, "reason": "",
    },
    "SUPPLY_UNAVAILABLE": {
        "label": "查看货源与采购", "kind": "ROUTE", "action": None,
        "path": "/app/supply/purchases", "connected": True, "reason": "",
    },
    # 素材/权利缺口（M2-D）：与「缺商品资料」分开。缺的是**图片权利证据**，
    # 去商品资料页补标题分类是白跑一趟；该补的是素材登记与授权证据。
    # `connected` 由上传能力决定（见下方 repair_action 的后处理），
    # 没接上传服务时只能看不能传，必须如实说。
    "ASSET_RIGHTS_MISSING": {
        "label": "去商品详情登记素材与权利证据", "kind": "ROUTE", "action": None,
        "path": "/app/products", "connected": True, "reason": "",
    },
    "STOCK_REQUIRED": {
        "label": "发起备货申请", "kind": "ACTION", "action": "REQUEST_STOCK",
        "path": "/app/fulfillment", "connected": False,
        "reason": "备货领域服务未接入（B03–B09），暂不能在流程内发起备货",
    },
    "USER_ACTION_REQUIRED": {
        "label": "去待办处理", "kind": "ROUTE", "action": None,
        "path": "/app/tasks", "connected": True, "reason": "",
    },
    "PLATFORM_PENDING": {
        "label": "等待平台回执", "kind": "UNAVAILABLE", "action": None,
        "path": "/app/launch", "connected": False,
        "reason": "平台侧尚未给出回执，本地无可补齐动作",
    },
    "PLATFORM_ERROR": {
        "label": "查看流程并重试同步", "kind": "UNAVAILABLE", "action": None,
        "path": "/app/launch", "connected": False,
        "reason": "平台返回无法映射的状态，需人工核对原始回执",
    },
    "EXTERNAL_SERVICE_REQUIRED": {
        "label": "该能力尚未接入", "kind": "UNAVAILABLE", "action": None,
        "path": "/app/launch", "connected": False,
        "reason": "所需外部服务未接入（B03–B09）",
    },
}

# 阻断码之外还有几类「动作层」错误需要指路（非业务门禁，但同样不能裸 409）。
_BUILTIN_FALLBACK = {
    "label": "在待办中心处理", "kind": "ROUTE", "action": None,
    "path": "/app/tasks", "connected": True,
    "reason": "该阻断暂无专用补齐入口，请在待办中心跟进",
}


def repair_action(code, *, business_type=None, product_id=None):
    """生成补齐入口；永不返回 None。

    :param code: 阻断码（`BLOCK_CODES` 的值或动作层错误码）
    :param business_type: 步骤业务类型，用于把 MISSING_DATA 细分到具体补齐目标
    :param product_id: 有商品上下文时把入口收敛到该商品详情页，而不是列表页
    """
    spec = _BY_CODE.get(code) or _BUILTIN_FALLBACK
    action = dict(spec)

    # 缺资料但属于材料类步骤：素材/合规/标签的补齐落在合规页，而不是商品资料。
    if code == "MISSING_DATA" and business_type in {"COMPLIANCE", "LABEL", "EVIDENCE"}:
        action = dict(_BY_CODE["COMPLIANCE_BLOCK"])

    # 素材缺口能不能真补齐取决于上传服务在不在：没接就标成不可完成并给原因，
    # 不能让用户点进去以后才发现「哈希填不出来」。
    if code == "ASSET_RIGHTS_MISSING":
        capability = asset_upload.capability()
        if not capability["connected"]:
            action["connected"] = False
            action["reason"] = (
                "素材上传服务未接入（未配置 ERP_ASSET_UPLOAD_DIR）：商品页可查看素材区，"
                "但不能登记新素材，也不会用客户端声明的哈希凑合")

    if type(product_id) is int and product_id > 0:
        if action["path"] == "/app/products":
            action["path"] = f"/app/products/{product_id}"
    return action
