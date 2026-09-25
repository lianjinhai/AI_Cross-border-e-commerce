"""客服 Agent：意图识别 + 按意图自动回复（对应规划第十三章）。"""
from datetime import datetime

from ..ai.knowledge import retrieve
from ..models import Conversation, Message, Order, Product
from .base import BaseAgent

_INTENT_KEYWORDS = {
    "order_status": ["订单", "发货", "到货", "下单", "order", "where is my", "delivered", "shipped"],
    "logistics": ["物流", "快递", "运单", "追踪", "tracking", "shipping", "delivery time", "多久"],
    "refund": ["退款", "退货", "换货", "refund", "return", "broken", "损坏", "质量"],
    "product_qa": ["尺寸", "材质", "颜色", "尺码", "怎么用", "size", "material", "color", "how to", "spec"],
}

_STATUS_CN = {"pending": "待支付", "paid": "已付款待发货", "shipped": "已发货",
              "delivered": "已签收", "refunded": "已退款"}


class SupportAgent(BaseAgent):
    name = "support"
    # Agent OS 合规状态：**未登记**。
    # 架构 §6.1 把「客服 Agent」明确列为禁止的员工角色式建模，而本类当前承担
    # 客服意图识别与自动回复，因此**不在 §7.1 的 8 个冻结 Agent 清单内**。
    # 这里显式置 None（而非悄悄留空）：任何调用 `SupportAgent.contract()` 的
    # 代码都会立刻抛错，从而暴露「这个 Agent 还没被架构接纳」这一事实。
    # 处置见 docs/DECISIONS.md D35 与规范 §11 债务台账 DEBT-34。
    agent_contract = None

    def classify(self, text: str) -> str:
        t = (text or "").lower()
        for intent, words in _INTENT_KEYWORDS.items():
            if any(w in t for w in words):
                return intent
        return "other"

    def _template(self, intent: str, conv: Conversation, text: str) -> str:
        if intent == "order_status":
            order = self.db.get(Order, conv.order_id) if conv.order_id else None
            if order:
                return (f"您好！您的订单 {order.external_no} 当前状态为「{_STATUS_CN.get(order.status, order.status)}」"
                        f"（{order.platform}，共 {order.qty} 件）。如有疑问随时告诉我～")
            return "麻烦提供一下订单号，我马上为您查询订单状态～"
        if intent == "logistics":
            return ("亲，您的包裹已交由国际物流承运，一般 7-15 个工作日送达。"
                    "您可在订单详情页点击「追踪物流」查看实时轨迹；若超时未更新，我们会主动为您处理。")
        if intent == "refund":
            return ("非常抱歉给您带来不好的体验！我们支持 7 天无理由退换货："
                    "请在订单页申请退款并上传问题照片，客服会优先为您处理；"
                    "如需人工协助，工作时间 2 小时内会有专属客服联系您。")
        if intent == "product_qa":
            info = ""
            if conv.product_id:
                p = self.db.get(Product, conv.product_id)
                if p:
                    a = p.attrs or {}
                    info = (f"您咨询的「{p.title}」：材质 {a.get('material', '详情见页面')}，"
                            f"重量 {a.get('weight_kg', '-')}kg，多色可选。")
            docs = retrieve(self.db, self.tenant_id, text, top_k=2)
            # M4：记录知识命中情况，供候选记录条件判断（复核修正 10）
            self._last_kb_hit = bool(docs)
            extra = f"相关说明：{docs[0]['content'][:120]}" if docs else ""
            return f"{info}更多规格信息可以告诉我您的需求，我来为您推荐~ {extra}".strip()
        return ("感谢您的留言！已收到您的问题，客服小姐姐会尽快回复；"
                "您也可以直接描述订单号+问题，我们能更快帮您解决~")

    def auto_reply(self, conversation_id: int) -> dict:
        self._last_kb_hit = False  # M4：知识命中标记（每次调用重置）
        conv = self.db.get(Conversation, conversation_id)
        if not conv or conv.tenant_id != self.tenant_id:
            raise ValueError(f"会话 {conversation_id} 不存在")
        # 待答问题文本由 knowledge_learning 统一提供：候选哈希与答案回填必须用
        # 完全一致的查询口径，两处各写一遍会漂移（回填失配或答非所问）。
        from ..services import knowledge_learning

        text = (knowledge_learning.latest_question_text(
            self.db, self.tenant_id, conversation_id) or "你好")
        intent = self.classify(text)

        def rule() -> dict:
            return {"reply": self._template(intent, conv, text), "intent": intent}

        system = "你是跨境电商多语言智能客服，语气温专业友好，不承诺无法兑现的事项。只返回 JSON。"
        prompt = (f"买家消息: {text[:500]}\n意图: {intent}；"
                  f"平台: {conv.platform}；订单状态: "
                  + (str(self.db.get(Order, conv.order_id).status) if conv.order_id else "无")
                  + "。请生成一条 80 字内的中文自动回复。"
                    "返回 JSON: {\"reply\":\"...\"}")
        result, _mode = self.ask_json("auto_reply", system, prompt, fallback=rule, small_task=True)
        reply = (result.get("reply") or "").strip()
        if not reply:
            reply = rule()["reply"]
        row = Message(tenant_id=self.tenant_id, conversation_id=conversation_id, role="agent",
                      content=reply, intent=result.get("intent", intent), auto=True)
        self.db.add(row)
        conv.last_message_at = datetime.utcnow()
        self.db.commit()

        # M4 知识自进化：仅当「意图未分类」或「知识库无任何命中」时记录候选
        # （复核修正 10：条件过宽会把"已有知识可参考"误判为未命中，产生噪音）
        kb_hit = getattr(self, "_last_kb_hit", False)
        self._last_kb_hit = False
        if intent == "other" or not kb_hit:
            from ..services import knowledge_learning

            knowledge_learning.record_candidate(
                self.db, self.tenant_id, text, intent, conversation_id=conversation_id)
        return {"id": row.id, "conversation_id": conversation_id, "role": "agent",
                "content": reply, "intent": row.intent, "auto": True,
                "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S")}
