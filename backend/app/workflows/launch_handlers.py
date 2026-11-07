"""Launch 业务处理器（B01 接通集）：资料完成、重试、取消；注册表供执行框架查找。

handler 只做领域前置校验并返回 StepEffect 断言（设计 D10），不自行提交事务、
不直接写库；落库、收敛与事件由 launch_actions 统一编排。触碰 AiAction/Attempt 的
提交/核验 handler 按设计 D1 二分集中在 launch_submit。
"""

from ..models import AiAction, PlatformPublishAttempt, Product, utcnow
from ..services import label_packages, pricing_rounds
from .launch_access import LaunchError
from .launch_action_catalog import ActionContext, StepEffect
from .launch_repair import repair_action
from .launch_state import facts_digest
from .launch_status import is_verified_online

# 基础 handler 注册表（文件末尾填充）；launch_submit.SUBMIT_HANDLERS 由
# launch_actions 合并进完整目录，避免 launch_handlers 前向引用提交/核验 handler。
HANDLERS: dict = {}


def complete_data(ctx: ActionContext) -> StepEffect:
    """商品资料完成：条件已由 NBA 门禁确定满足；固定证据并断言 COMPLETED。

    证据四要素固定为 {input_revision, facts_digest, completed_by, completed_at}（AC-5.1）；
    条件不满足时 409 且 blockers 复用 asset_rights.reasons（AC-5.2），步骤保持 READY。
    """
    step = ctx.step
    target = (ctx.plan.get("steps") or {}).get(step.step_code) or {}
    if target.get("completion_satisfied") is not True:
        raise LaunchError("ACTION_PRECONDITION_FAILED", "完成条件尚未被服务端事实满足", 409,
                          blockers=missing_blockers(ctx.facts, step))
    digest = facts_digest(ctx.facts, ctx.predicates)
    evidence = {"input_revision": step.input_revision, "facts_digest": digest,
                "completed_by": ctx.current.user_id, "completed_at": utcnow().isoformat()}
    return StepEffect(status="COMPLETED", result=evidence,
                      evidence_refs=["facts:%s" % digest[:16]],
                      receipt={"step_code": step.step_code, "step_status": "COMPLETED",
                               "evidence_digest": digest, "evidence": evidence})


def retry_step(ctx: ActionContext) -> StepEffect:
    """FAILED → READY（经规则重算）：attempts+1，事件记 predecessor（AC-8.1）。

    外部结果待核查（Attempt uncertain 或 AiAction EXECUTING）时禁止重发（AC-8.2）。
    """
    step = ctx.step
    _reject_pending_external(ctx)
    predecessor = {"previous_status": step.step_status}
    action_id = (step.result or {}).get("action_id")
    action = ctx.db.get(AiAction, action_id) if type(action_id) is int else None
    if action is not None:
        predecessor["action_id"] = action.id
        predecessor["action_status"] = action.status
    return StepEffect(status="READY", attempts_delta=1,
                      result={"retried_at": utcnow().isoformat()},
                      receipt={"step_code": step.step_code, "step_status": "READY",
                               "predecessor": predecessor, "attempts": step.attempts + 1})


def cancel_run(ctx: ActionContext) -> StepEffect:
    """CANCEL/ABANDON_PRODUCT 同语义终止本轮（AC-8.3/8.6）：纯本地终态 + 事件，
    不调用任何外部下架/退款；已核验在售或已完成流程一律 409（AC-7.6/8.4）。
    """
    run = ctx.run
    if run.ended_at is not None or run.execution_status == "CANCELLED":
        raise LaunchError("LAUNCH_ENDED", "已结束的流程不能重复取消", 409)
    if is_verified_online(run):
        raise LaunchError("ACTION_PRECONDITION_FAILED", "已核验在售的流程不能取消", 409)
    if run.execution_status == "COMPLETED":
        raise LaunchError("ACTION_PRECONDITION_FAILED", "已完成的流程不能取消", 409)
    now = utcnow()
    return StepEffect(cancelled=True, run_fields={"ended_at": now, "active_slot": None},
                      receipt={"ended_at": now.isoformat(), "active_slot_released": True,
                               "note": ctx.payload.get("note", "")})


#: 素材权利没有具体缺项时的兜底原因（`evaluate_asset_rights` 通过但完成条件仍未满足）。
GENERIC_MISSING_REASON = "完成条件尚未满足"


def _missing_code(step, asset_reasons):
    """缺项归属哪个阻断码：素材/权利缺口 ≠ 商品资料缺口。

    以前一律 `MISSING_DATA`，于是「缺图片权利证据」的用户被指去「补充商品资料」，
    到了商品页才发现那里根本没有素材与授权入口——跑一趟白跑。
    `asset_rights_allowed` 参与完成条件的只有 `DATA_PREPARATION` 与
    `PLATFORM_ACTIVATION`；后者没有 `COMPLETE_DATA` 动作，所以这里只区分资料类步骤，
    材料类（COMPLIANCE/LABEL/EVIDENCE）仍按原样落到 `MISSING_DATA` → 合规页。
    """
    if asset_reasons and step.business_type == "DATA_PREPARATION":
        return "ASSET_RIGHTS_MISSING"
    return "MISSING_DATA"


def missing_blockers(facts, step):
    """把素材权利等具体缺项转成 blockers（AC-5.2：前端可逐条展示）。

    P0-4：每项都带补齐入口，前端才能给出「下一步去哪」，而不是只有一句原因。
    M2-D：入口要指对地方——缺素材就给素材登记入口，缺商品资料才给 `COMPLETE_DATA`。
    """
    asset_reasons = list((facts.get("assets") or {}).get("reasons") or [])
    reasons = asset_reasons or [GENERIC_MISSING_REASON]
    product_id = (facts.get("product") or {}).get("id")
    code = _missing_code(step, asset_reasons)
    # 一次构造：`asset://` 上传能力一致，所以整批缺项共用同一个补齐入口。
    action = repair_action(code, business_type=step.business_type, product_id=product_id)
    return [{"code": code, "message": reason, "step_code": step.step_code,
             "owner_actor": step.actor, "evidence_refs": [], "repair_action": dict(action)}
            for reason in reasons]


def report_price(ctx: ActionContext) -> StepEffect:
    """REPORT_PRICE（M2-A）：落一轮**我方申报价**，过低价门禁后完成「平台核价」步骤。

    语义边界（写在函数里，避免以后被当成平台往返）：
    本批核价是**本地报价轮次**——记录申报价、成本来源快照与门槛判定，由人工在
    PRICE_DECISION 决策；**没有**向平台发送报价的适配器，所以这里不写任何外部引用，
    也不声称「平台已核价」。`PRICE_REVIEW` 完成只代表本地评审记录成立。
    """
    quote = _price_quote(ctx)
    _require_margin_ok(ctx.step, quote)
    row = pricing_rounds.append(
        ctx.db, tenant_id=ctx.run.tenant_id, product_id=ctx.run.product_id, action="REPORT",
        quote_result=quote, run_id=ctx.run.id, step_code=ctx.step.step_code,
        created_by=ctx.current.user_id)
    return _price_effect(ctx, row, quote, status="COMPLETED")


def counter_price(ctx: ActionContext) -> StepEffect:
    """COUNTER_PRICE（M2-A）：还价 = 新报一轮，决策置 COUNTER，决策步骤**不**完成。

    还价后必须重新有一轮被接受，`PRICE_DECISION` 才可能完成——否则「还了价却直接放行」
    会把没谈拢的价格当成谈拢了。
    """
    quote = _price_quote(ctx)
    _require_margin_ok(ctx.step, quote)
    row = pricing_rounds.append(
        ctx.db, tenant_id=ctx.run.tenant_id, product_id=ctx.run.product_id, action="COUNTER",
        quote_result=quote, run_id=ctx.run.id, step_code=ctx.step.step_code,
        created_by=ctx.current.user_id, decision=_decision(ctx, "COUNTER"))
    return _price_effect(ctx, row, quote)


def accept_price(ctx: ActionContext) -> StepEffect:
    """ACCEPT_PRICE（M2-A）：接受最新报价轮次；接受前**按当前成本重算**，不拿旧快照放行。

    成本可能已经变了（供应商调价、汇率变动），所以接受时重算一次毛利：
    重算不过门禁就当场重新阻断，而不是让一个「当时能过」的价在成本变化后静默生效。
    """
    review = pricing_rounds.latest_review(ctx.db, ctx.run.tenant_id, ctx.run.product_id,
                                          run_id=ctx.run.id)
    if review is None:
        raise LaunchError("ACTION_PRECONDITION_FAILED", "还没有可接受的价格：请先申报报价轮次", 409,
                          blockers=[{"code": "USER_ACTION_REQUIRED",
                                     "message": "还没有报价轮次，先申报一轮再决定接受与否",
                                     "step_code": ctx.step.step_code,
                                     "owner_actor": ctx.step.actor, "evidence_refs": [],
                                     "repair_action": repair_action("USER_ACTION_REQUIRED")}])
    quote = _quote(ctx, review.price, review.currency)
    _require_margin_ok(ctx.step, quote)
    row = pricing_rounds.append(
        ctx.db, tenant_id=ctx.run.tenant_id, product_id=ctx.run.product_id, action="ACCEPT",
        quote_result=quote, run_id=ctx.run.id, step_code=ctx.step.step_code,
        created_by=ctx.current.user_id, decision=_decision(ctx, "ACCEPT", source=review))
    return _price_effect(ctx, row, quote, status="COMPLETED")


def _price_quote(ctx: ActionContext) -> dict:
    """从载荷取价与币种（币种必填）并算一轮毛利；类型错误 422、算不出成本 409。"""
    price = ctx.payload.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float, str)):
        raise LaunchError("ACTION_PAYLOAD_INVALID", "报价必须是数字", 422)
    return _quote(ctx, price, ctx.payload.get("currency"))


def _quote(ctx: ActionContext, price, currency) -> dict:
    try:
        return pricing_rounds.quote(ctx.db, ctx.run.tenant_id, ctx.run.product_id,
                                    price, currency, shop_id=ctx.run.shop_id)
    except pricing_rounds.PriceRoundError as exc:
        status = 422 if exc.code in {"CURRENCY_REQUIRED", "PRICE_INVALID"} else 409
        raise LaunchError("ACTION_PAYLOAD_INVALID" if status == 422 else "ACTION_PRECONDITION_FAILED",
                          exc.message, status) from exc


def _require_margin_ok(step, quote):
    """低价门禁：毛利低于门槛即阻断，原因带两个具体数字，补齐入口指向定价页。"""
    if quote["margin_ok"]:
        return
    repair = repair_action("PRICE_UNACCEPTABLE", business_type=step.business_type)
    raise LaunchError(
        "ACTION_PRECONDITION_FAILED",
        "售价毛利 %.1f%% 低于最低要求 %.1f%%，不能提交核价" % (
            quote["margin"] * 100, quote["min_margin"] * 100), 409,
        blockers=[{"code": "PRICE_UNACCEPTABLE",
                   "message": "售价毛利 %.1f%% 低于最低要求 %.1f%%，不能提交核价" % (
                       quote["margin"] * 100, quote["min_margin"] * 100),
                   "step_code": step.step_code, "owner_actor": step.actor,
                   "evidence_refs": [], "repair_action": repair}])


def _decision(ctx: ActionContext, decision: str, source=None) -> dict:
    """人工决定留痕：谁、什么时候、依据哪一轮、备注原文（note 已由载荷契约截断）。"""
    return {"decision": decision, "by": ctx.current.user_id,
            "actor_role": getattr(ctx.current, "role", ""),
            "at": utcnow().isoformat(), "note": ctx.payload.get("note", ""),
            "source_round_id": source.id if source is not None else None}


def _price_effect(ctx: ActionContext, row, quote, *, status: str | None = None) -> StepEffect:
    """把刚写下的轮次转成收敛用的新事实与新谓词（不落 step.result 的调度字段）。

    ``cost_snapshot_current`` 之所以现在就能置 True：轮次是用**本次实时成本**算出来的，
    指纹天然等于当前成本；下次请求若成本已变，`launch_facts` 会重算出 False 并重新阻断。
    """
    facts = pricing_rounds.pricing_facts(ctx.db, ctx.run.tenant_id, ctx.run.product_id,
                                         run_id=ctx.run.id)
    result = {"pricing_round_id": row.id, "round_no": row.round_no, "action": row.action,
              "price": row.price, "currency": row.currency, "margin": row.margin,
              "min_margin": row.min_margin, "margin_ok": bool(row.margin_ok),
              "cost_fingerprint": row.cost_fingerprint}
    receipt = {"step_code": ctx.step.step_code, "round_id": row.id, "round_no": row.round_no,
               "action": row.action, "price": row.price, "currency": row.currency,
               "margin": row.margin, "min_margin": row.min_margin,
               "margin_ok": bool(row.margin_ok), "target_margin": quote["target_margin"],
               "decision": (row.decision or {}).get("decision"),
               "cost_snapshot_current": True,
               "note": "本地报价轮次；未向平台发送报价（无核价适配器）"}
    return StepEffect(status=status, result=result, receipt=receipt,
                      facts={"pricing": facts},
                      predicates={"cost_snapshot_current": {"PRICE_REVIEW": True}},
                      evidence_refs=["price_round:%s" % row.id])


def generate_label(ctx: ActionContext) -> StepEffect:
    """GENERATE_LABEL（M2-E）：依据充分才生成第一版标签包。

    语义边界（写在函数里，避免以后被当成平台往返）：
    本批标签是**本地生成的标签包**——只拼出可核对的标签字段（SKU、品名、原产国、
    已核验的认证声明与要求说明），**没有**打印、上传或向平台发送任何东西。
    `LABEL_PREPARATION` 完成只代表「存在一版依据充分的标签包」。

    依据不足时抛 409 并**逐条**给出缺什么（哪个要求缺证据 / 哪条已过期 / 该国要求未收录），
    每条都带补齐入口；此时一行业务数据都不写。
    """
    return _generate(ctx, action="GENERATE")


def regenerate_label(ctx: ActionContext) -> StepEffect:
    """REGENERATE_LABEL（M2-E）：依据变化或需改版时追加新版本，旧版本永久保留。

    没有旧版时 409：否则「重新生成」会凭空造出第一版，让依据失效这件事看起来
    像「改过一版」——历史版本号与审计链就对不上了。
    """
    return _generate(ctx, action="REGENERATE")


def _generate(ctx: ActionContext, *, action: str) -> StepEffect:
    try:
        row = label_packages.generate(
            ctx.db, tenant_id=ctx.run.tenant_id, product=_product(ctx), shop_id=ctx.run.shop_id,
            country=ctx.run.market, run_id=ctx.run.id,
            step_code=ctx.step.step_code if ctx.step else "", action=action,
            created_by=ctx.current.user_id, require_existing=(action == "REGENERATE"))
    except label_packages.LabelBasisError as exc:
        raise _label_blocked(ctx, exc) from exc
    return _label_effect(ctx, row)


def _product(ctx):
    product = ctx.db.get(Product, ctx.run.product_id, populate_existing=True)
    if product is None or product.tenant_id != ctx.run.tenant_id:
        raise LaunchError("LAUNCH_TARGET_INVALID", "流程商品不存在或不属于当前租户", 409)
    return product


def _label_blocked(ctx, exc) -> LaunchError:
    """依据不足的 409：每个缺项一条 blocker，都指向「去商品详情补目的国合规证据」。"""
    step = ctx.step
    business_type = step.business_type if step else "LABEL"
    repair = repair_action(exc.code, business_type=business_type, product_id=ctx.run.product_id)
    reasons = exc.reasons or [exc.message]
    return LaunchError("ACTION_PRECONDITION_FAILED", exc.message, 409,
                       blockers=[{"code": exc.code, "message": reason,
                                  "step_code": step.step_code if step else "",
                                  "owner_actor": step.actor if step else "SYSTEM",
                                  "evidence_refs": [], "repair_action": dict(repair)}
                                 for reason in reasons])


def _label_effect(ctx: ActionContext, row) -> StepEffect:
    """把刚写下的标签包转成收敛用的新事实与新谓词（不落 step.result 的调度字段）。

    ``LABEL_PACKAGE`` 之所以现在就能置 True：这一版是用**本次实时依据**生成的，
    指纹天然等于当前依据；下次请求若证据过期或被改，`launch_facts` 会重算出 False
    并让步骤重新阻断。
    """
    facts = label_packages.label_facts(ctx.db, ctx.run.tenant_id, _product(ctx),
                                       ctx.run.shop_id, row.destination_country) or {}
    result = {"label_package_id": row.id, "label_version": row.version,
              "destination_country": row.destination_country,
              "content_digest": row.content_digest,
              "basis_fingerprint": row.basis_fingerprint,
              "open_items": list(row.open_items or [])}
    receipt = {"step_code": ctx.step.step_code if ctx.step else "", "package_id": row.id,
               "version": row.version, "action": row.action,
               "destination_country": row.destination_country,
               "content_digest": row.content_digest,
               "marks": [item.get("requirement") for item in (row.content or {}).get("marks") or []],
               "open_items": list(row.open_items or []),
               "label_package_current": True,
               "note": "本地生成的标签包；未打印、未上传、未向平台发送"}
    return StepEffect(status="COMPLETED", result=result, receipt=receipt,
                      facts={"label": facts},
                      predicates={"verified_artifact": {"LABEL_PACKAGE": True}},
                      evidence_refs=["label_package:%s" % row.id])


def _reject_pending_external(ctx):
    """外部结果待核查时不重发（AC-8.2）：Attempt uncertain 或 AiAction EXECUTING。"""
    step = ctx.step
    if step.business_type != "PLATFORM_SUBMISSION":
        return
    attempt = ctx.db.query(PlatformPublishAttempt).filter_by(
        tenant_id=ctx.run.tenant_id, listing_id=ctx.run.listing_id,
        shop_id=ctx.run.shop_id, platform=ctx.run.platform).first()
    if attempt is not None and attempt.status == "uncertain":
        raise LaunchError("ACTION_PRECONDITION_FAILED", "外部结果待核查，请先同步核对", 409)
    action_id = (step.result or {}).get("action_id")
    action = ctx.db.get(AiAction, action_id) if type(action_id) is int else None
    if action is not None and action.status == "EXECUTING":
        raise LaunchError("ACTION_PRECONDITION_FAILED", "外部结果待核查，请先同步核对", 409)


HANDLERS.update({"COMPLETE_DATA": complete_data, "RETRY": retry_step,
                 "CANCEL": cancel_run, "ABANDON_PRODUCT": cancel_run,
                 "REPORT_PRICE": report_price, "COUNTER_PRICE": counter_price,
                 "ACCEPT_PRICE": accept_price,
                 "GENERATE_LABEL": generate_label, "REGENERATE_LABEL": regenerate_label})
