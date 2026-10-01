"""合规纯分析：规则底线、有限值校验和不可变输入；不保存任何数据。"""

import math
import re

from .ai_actions import ActionError

BRANDS = ["apple", "iphone", "ipad", "samsung", "xiaomi", "nike", "adidas", "puma",
          "disney", "marvel", "lego", "barbie", "hello kitty", "pokemon", "rolex",
          "louis vuitton", "gucci", "chanel", "cartier", "dyson", "anker"]
CLAIMS = ["最好", "第一品牌", "顶级", "no.1", "#1", "cure", "fda approved",
          "杀菌", "防癌", "治疗", "100% safe", "100% safe", "medical"]
QUERIES = [("商标黑名单 品牌 侵权", 2), ("违禁词 商标 图片 平台规则", 3)]
RANK = {"low": 0, "mid": 1, "high": 2}


def inputs(target_type, target, product, knowledge):
    fields = (["id", "title", "attrs", "images", "status"] if target_type == "product"
              else ["id", "product_id", "platform", "title", "description", "bullets", "keywords"])
    return {"version": 1, "target_type": target_type,
            "target": {key: target.get(key) for key in fields},
            "product": {key: product.get(key) for key in ("id", "title", "attrs", "images", "status")},
            "knowledge": knowledge, "rules": {"brands": BRANDS, "claims": CLAIMS}}


def rule_analysis(basis):
    target = basis["target"]
    text = (target["title"] + " " + str(target.get("attrs") or {})
            if basis["target_type"] == "product" else " ".join(
                [target["title"], target["description"]] + list(target["bullets"] or [])
                + list(target["keywords"] or []))).lower()
    # 保留既有 Listing images=[] 口径与重复宣称扣分；不在迁移中默改规则。
    images = target.get("images") or []
    brands = set(BRANDS)
    for doc in basis["knowledge"].get("brands", []):
        brands |= {word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9 ]{1,20}", doc["content"])
                   if word.strip().lower() in BRANDS or len(word.strip()) > 3}
    issues = [{"type": "brand", "level": "high", "detail": f"文本命中品牌词「{word}」，存在商标侵权风险",
               "evidence": word} for word in sorted(brands) if word in text]
    issues += [{"type": "claim", "level": "mid", "detail": f"命中违禁宣称「{word}」，违反广告法/平台规则",
                "evidence": word} for word in CLAIMS if word in text]
    if not images:
        issues.append({"type": "image", "level": "mid", "detail": "缺少商品图片，无法核验素材合规", "evidence": "images=[]"})
    for url in images:
        if any(hint in url.lower() for hint in ("watermark", "logo_", "_logo", "shuiyin")):
            issues.append({"type": "image", "level": "mid", "detail": f"图片疑似带水印/第三方LOGO: {url[:80]}", "evidence": url[:120]})
    score = max(0.0, 100 - sum(50 if item["level"] == "high" else 15 for item in issues))
    suggestions = {"brand": "删除该品牌词，改用通用描述（如 smartphone case 而非 iPhone case）",
                   "claim": "删除绝对化/违禁宣称，改为客观功能描述", "image": "更换为自有拍摄或已授权图片，避免水印与第三方LOGO"}
    return {"issues": issues, "score": score, "risk_level": score_risk(score),
            "suggestions": sorted({suggestions[item["type"]] for item in issues})}


def score_risk(score):
    return "high" if score < 60 else ("mid" if score < 85 else "low")


def validate_result(result, floor):
    if not isinstance(result, dict) or result.get("risk_level") not in RANK:
        raise ActionError(400, "合规风险等级无效")
    score = result.get("score")
    if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 100:
        raise ActionError(400, "合规分数必须是 0～100 的有限值")
    issues, suggestions = result.get("issues"), result.get("suggestions")
    if (not isinstance(issues, list) or not isinstance(suggestions, list)
            or any(not isinstance(item, str) for item in suggestions)):
        raise ActionError(400, "合规问题或建议字段无效")
    for item in issues:
        if (not isinstance(item, dict) or item.get("type") not in {"brand", "claim", "image", "platform"}
                or item.get("level") not in RANK or any(not isinstance(item.get(k), str) for k in ("detail", "evidence"))):
            raise ActionError(400, "合规问题结构无效")
    required = max([RANK[floor["risk_level"]], RANK[score_risk(score)]]
                   + [2 if item["level"] == "high" else 0 for item in issues])
    if score > floor["score"] or RANK[result["risk_level"]] < required:
        raise ActionError(409, "合规分析低于确定性规则风险底线")
    if any(item not in issues for item in floor["issues"]):
        raise ActionError(409, "合规分析遗漏规则命中的问题")
    return {key: result[key] for key in ("risk_level", "score", "issues", "suggestions")}
