"""审计落库前的 PII 脱敏（Agent OS §19 验收项 8「无 PII 泄漏」）。

为什么必须在**写入前**脱敏
    `ai_logs` 是长期保留的审计表（§16 Trace 的落地表）。PII 一旦落库，回收要靠
    数据清理 + 冷备，代价高且容易漏。实测主库已有 2 行 `support.auto_reply` 的
    prompt 含买家消息原文（第二十七轮交接记录）——那正是「先落库、再想办法」的
    结果。因此脱敏挂在两个唯一写入落点上：`BaseAgent._log` 与 `tools.audit`，
    而不是散落到各 Agent（T-53：同一件事只维护一份）。

为什么不做哈希、也不整段丢弃
    审计要回答「当时读了/写了哪一类数据、有多长」，不是「原文是什么」。整段丢弃
    会让 §19 验收项 5（全部可追溯）落空；哈希则给出「可复原」的错觉（手机号空间
    很小，字典攻击成本极低）。折中：替换为**带长度线索的标记**。

为什么放在 services/ 而不是 agents/
    `agents/`（写 AiLog）与 `tools/`（写 Tool 审计）都要用它，而依赖方向是
    `agents -> tools -> services`——红线 L-7 禁止 `tools/` 反向依赖 `agents/`。
    `services/` 是唯一对两者都合法的落点。

覆盖范围与残留风险
    覆盖：手机号 / 邮箱 / 身份证号 / 凭证（Token、API Key、密码）/ `买家消息:` 正文
    （含多行，直到下一个字段行）。
    未覆盖：订单号、买家姓名（属业务标识，业务表保留原文，审计只记「当时带过」。
    新增 PII 形态时只需在 `_PATTERNS` 加一条，两处调用点无需改动）。
    `BaseAgent.record_decision` 的 decision/evidence 不在本模块范围——该方法约定
    只存引用（见其文档字符串），不存全量快照。
"""
from __future__ import annotations

import re

MASK_PHONE = "[手机号]"
MASK_EMAIL = "[邮箱]"
MASK_ID_CARD = "[身份证]"
MASK_CREDENTIAL = "[凭证]"

# 大陆手机号：11 位、1 开头、第二位 3-9。前后用 (?<!\d)/(?!\d) 卡边界，否则会把
# 「订单号 1790212224」这类更长数字串中的片段误判成手机号（业务标识不该被改写）。
_PATTERNS = (
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), MASK_PHONE),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), MASK_EMAIL),
    (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), MASK_ID_CARD),
    # 凭证（§15.4 与买家 PII 同级）：`token=xxx` / `Bearer xxx` / `api_key: xxx` 形态。
    # 值要求 6 位以上字母数字，避免把「secret sauce」这类普通文本误伤。
    (re.compile(r"(?i)\b(?:bearer|token|api[_-]?key|access[_-]?key|secret|password|passwd)"
                r"\b\s*[:=]?\s*[A-Za-z0-9._\-]{6,}"), MASK_CREDENTIAL),
)

# 「买家消息: <正文>」整段正文（可跨行，直到下一个「字段:」行或字符串结尾）。
# 客服类 prompt 的主要泄漏源，且形态固定，因此按结构遮，而不是靠关键词猜。
# 组 1 含冒号后的空白：长度线索只数正文，不把分隔空格算进去（否则标记字数比原文多 1）。
_BUYER_LINE = re.compile(
    r"(买家消息\s*[:：]\s*)(.*?)(?=\n\s*[^\s\n:：]{1,12}[:：]|\Z)", re.S)


def redact(text) -> str:
    """按模式替换可识别个人的片段（手机号 / 邮箱 / 身份证号）。"""
    out = "" if text is None else str(text)
    for pattern, mask in _PATTERNS:
        out = pattern.sub(mask, out)
    return out


def redact_prompt(text) -> str:
    """prompt 专用：先遮「买家消息」正文（保留长度线索），再做模式替换。

    顺序有意：先遮正文，正文里的手机号等就不会以「正文片段」的形式残留。
    """
    out = "" if text is None else str(text)
    out = _BUYER_LINE.sub(
        lambda m: "%s[已脱敏·原文 %d 字]" % (m.group(1), len(m.group(2))), out)
    return redact(out)
