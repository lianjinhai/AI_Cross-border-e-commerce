"""PII 脱敏回归测试（Agent OS §19 验收项 8：Trace / Memory / AiLog 无买家 PII）。

为什么必须有：脱敏是「看不见的修复」——没有断言时，任何人把 `_log` 改回
`prompt[:4000]` 都不会有测试变红，而 PII 已经开始重新落库（实测主库存量 2 行
就是这么来的）。因此本文件既测脱敏函数本身，也测**真实链路**（API → Agent →
`ai_logs`），并配一条反向断言：业务表必须保持原文。
"""

_PHONE = "13812345678"
_EMAIL = "buyer@example.com"
_ID_CARD = "110101199003071234"


def test_redact_masks_phone_email_and_id_card():
    from app.services.pii_redact import redact

    out = redact("联系 %s 或 %s，身份证 %s" % (_PHONE, _EMAIL, _ID_CARD))
    assert _PHONE not in out and _EMAIL not in out and _ID_CARD not in out
    assert "[手机号]" in out and "[邮箱]" in out and "[身份证]" in out


def test_redact_keeps_non_pii_text_untouched():
    """判别力反向：普通文本不得被改写——否则审计失去可读性，且掩盖真实内容。"""
    from app.services.pii_redact import redact

    text = "订单 1790212224 状态 shipped；数量 3 件；金额 19.99 USD"
    assert redact(text) == text


def test_redact_masks_credentials():
    """§15.4：Token / API Key / 密码与买家 PII 同级，禁止明文入库。"""
    from app.services.pii_redact import redact

    out = redact("Authorization: Bearer sk-abc123def456；api_key=AKIA1234567890")
    assert "sk-abc123def456" not in out and "AKIA1234567890" not in out
    assert "[凭证]" in out


def test_redact_keeps_short_secret_word_untouched():
    """判别力反向：普通英文词（secret + 短词）不得被当成凭证改写。"""
    from app.services.pii_redact import redact

    text = "secret sauce"
    assert redact(text) == text


def test_redact_prompt_masks_buyer_message_and_keeps_length_hint():
    from app.services.pii_redact import redact_prompt

    body = "请问支持批量采购折扣吗1790212224"
    prompt = "买家消息: %s\n意图: other；平台: shopee" % body
    out = redact_prompt(prompt)
    assert body not in out
    assert "[已脱敏·原文 %d 字]" % len(body) in out
    assert "意图: other；平台: shopee" in out, "脱敏不得吃掉审计要用的结构字段"


def test_redact_prompt_masks_multi_line_buyer_message():
    """多行买家消息也必须整段遮住（第二行不能漏）。"""
    from app.services.pii_redact import redact_prompt

    prompt = "买家消息: 第一行\n第二行也有内容\n意图: refund；平台: shopee"
    out = redact_prompt(prompt)
    assert "第一行" not in out and "第二行也有内容" not in out
    assert "意图: refund；平台: shopee" in out


def test_auto_reply_audit_has_no_buyer_pii(client, auth_headers):
    """端到端：买家消息原文不得进入 `ai_logs`，业务表必须保持原文。"""
    from app.db import SessionLocal
    from app.models import AiLog, Message

    buyer_text = "请问支持批量采购折扣吗%s" % _PHONE
    made = client.post("/api/support/conversations", headers=auth_headers, json={
        "platform": "shopee", "buyer_name": "PII探针买家", "content": buyer_text})
    assert made.status_code == 200, made.text
    cid = made.json()["id"]
    r = client.post("/api/support/conversations/%d/auto_reply" % cid, headers=auth_headers)
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        row = (db.query(AiLog).filter(AiLog.action == "auto_reply")
               .order_by(AiLog.id.desc()).first())
        assert row is not None, "auto_reply 未写审计（本用例失去判别力）"
        prompt = row.prompt or ""
        buyer_msg = (db.query(Message)
                     .filter(Message.conversation_id == cid, Message.role == "buyer")
                     .order_by(Message.id.desc()).first())
        assert buyer_msg is not None
        business_content = buyer_msg.content
    finally:
        db.close()

    assert _PHONE not in prompt, "手机号泄漏进 ai_logs"
    assert "批量采购折扣" not in prompt, "买家消息原文泄漏进 ai_logs"
    assert "[已脱敏" in prompt, "脱敏标记缺失——脱敏被静默回退？"
    # 反向断言：脱敏只作用于审计表，业务数据必须保持原文（否则客服看不到买家消息）
    assert buyer_text in business_content
