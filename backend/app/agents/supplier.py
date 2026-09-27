"""供应链 Agent：最优货源匹配 / 供应商评分 / 销量预测与缺货预警（对应规划第十四章）。

§18.3 第 2 步：读取全部经 Tool 层；写路径（评分快照 / 预测快照）集中标注，
属第 3 步（Action 层）欠账。
"""
import math
from datetime import datetime, timedelta

from ..models import ForecastSnapshot, SupplierScore
from .base import BaseAgent
from .contracts import CONTRACTS


class SupplierAgent(BaseAgent):
    name = "supplier"
    # Agent OS §6.2 契约（§18.3 第 1 步）：声明能力边界，供 Guardrail / Runtime 读取。
    agent_contract = CONTRACTS["supply_intelligence"]

    # ---- 读取：全部经 Tool 层（§18.3 第 2 步）----
    def _offers(self, **filters) -> list[dict]:
        """读报价走 Supply Tool；读不到时返回空列表，由调用方按「无报价」处理。"""
        got = self.tool("supply").call("get_supplier_offers", **filters)
        return got.data if got.ok and isinstance(got.data, list) else []

    def _suppliers(self, **filters) -> list[dict]:
        got = self.tool("supply").call("search_suppliers", **filters)
        return got.data if got.ok and isinstance(got.data, list) else []

    def _offer_stats(self, **filters) -> dict:
        got = self.tool("supply").call("get_offer_stats", **filters)
        return got.data if got.ok and isinstance(got.data, dict) else {}

    def _product(self, product_id) -> dict:
        got = self.tool("product").call("get_products", product_id=product_id)
        rows = got.data if got.ok and isinstance(got.data, list) else []
        if not rows:
            raise ValueError(f"商品 {product_id} 不存在")
        return rows[0]

    def _daily_sales(self, product_id: int, days: int = 84,
                     platform: str = "", country: str = "") -> list[dict]:
        got = self.tool("order").call("get_daily_sales", product_id=product_id, days=days,
                                      platform=platform, country=country)
        return got.data if got.ok and isinstance(got.data, list) else []

    # ---------------- 最优货源 ----------------
    def match_best(self, product_id: int) -> dict:
        """按 价格40% + 发货时效30% + 供应商口碑30% 选最优报价。"""
        offers = self._offers(product_id=product_id, in_stock=True, limit=200)
        if not offers:
            return {}
        # 供应商档案一次取回：逐个查会产生 N 次调用与 N 行审计（同一个目标）。
        by_id = {s["id"]: s for s in self._suppliers(
            supplier_ids=[o["supplier_id"] for o in offers], limit=200)}
        # 与旧 INNER JOIN 等价：报价的供应商不可见时该报价不参与评选。
        rows = [(o, by_id[o["supplier_id"]]) for o in offers if o["supplier_id"] in by_id]
        if not rows:
            return {}
        prices = [o["price"] for o, _ in rows]
        pmin, pmax = min(prices), max(prices)
        best, best_score = None, -1.0
        for offer, sup in rows:
            price_score = 100 if pmax == pmin else 100 * (pmax - offer["price"]) / (pmax - pmin)
            ship_score = max(0.0, 100 - offer["ship_days"] * 8)
            trust = (sup["rating"] / 5 * 50 + sup["stability"] / 2)
            score = 0.4 * price_score + 0.3 * ship_score + 0.3 * trust
            if score > best_score:
                best, best_score = (offer, sup), score
        offer, sup = best
        return {
            "product_id": product_id,
            "supplier": {"id": sup["id"], "name": sup["name"], "region": sup["region"],
                         "rating": sup["rating"], "ship_days": sup["ship_days"],
                         "stability": sup["stability"]},
            "offer": {"id": offer["id"], "price": offer["price"], "moq": offer["moq"],
                      "ship_days": offer["ship_days"], "in_stock": offer["in_stock"]},
            "reason": f"综合得分 {best_score:.0f}：价格 ¥{offer['price']}、"
                      f"{offer['ship_days']} 天发货、供应商评分 {sup['rating']}（{sup['name']}）",
        }

    def match_best_batch(self, params: dict | None = None, context: dict | None = None) -> dict:
        params, context = params or {}, context or {}
        ids = params.get("product_ids") or context.get("product_ids") or []
        matches, offers_patch = [], {}
        for pid in ids[:200]:
            r = self.match_best(int(pid))
            if not r:
                continue
            matches.append({"product_id": r["product_id"], "supplier_id": r["supplier"]["id"],
                            "supplier_name": r["supplier"]["name"], "offer_id": r["offer"]["id"],
                            "price": r["offer"]["price"], "ship_days": r["offer"]["ship_days"]})
            offers_patch[str(r["product_id"])] = {"supplier_id": r["supplier"]["id"],
                                                  "price": r["offer"]["price"],
                                                  "ship_days": r["offer"]["ship_days"]}
        return {"matches": matches, "context_patch": {"offers": offers_patch}}

    # ---------------- 供应商评分 ----------------
    def score_supplier(self, supplier_id: int) -> dict:
        sups = self._suppliers(supplier_ids=[supplier_id], limit=1)
        if not sups:
            raise ValueError(f"供应商 {supplier_id} 不存在")
        sup = sups[0]
        # 均价与全站均价都在 SQL 侧聚合：报价条数上限（200）不会污染这里的均值。
        avg_price = float(self._offer_stats(supplier_id=supplier_id).get("avg_price") or 0)
        all_avg = float(self._offer_stats().get("avg_price") or 0) or avg_price or 1
        quality = round(sup["rating"] / 5 * 100, 1)
        cost = round(max(0.0, 100 - (avg_price / all_avg - 0.8) * 100), 1) if avg_price else 60.0
        delivery = round(max(0.0, (14 - sup["ship_days"]) / 14 * 100), 1)
        stability = round(sup["stability"], 1)
        total = round(0.35 * quality + 0.25 * cost + 0.2 * delivery + 0.2 * stability, 1)
        reasons = [
            f"平台评分 {sup['rating']}/5 → 质量 {quality}",
            f"均价 ¥{avg_price:.2f}（全站均价 ¥{all_avg:.2f}）→ 成本 {cost}",
            f"{sup['ship_days']} 天发货 → 时效 {delivery}",
            f"履约稳定性 {stability}",
        ]
        row = SupplierScore(tenant_id=self.tenant_id, supplier_id=supplier_id,
                            quality=quality, cost=cost, delivery=delivery,
                            stability=stability, total=total, reasons=reasons, model="rule")
        # 写路径（新建评分快照）：§18.3 第 3 步（Action 层）欠账，见 D41。
        self.db.add(row)
        self.db.commit()
        return {"supplier_id": supplier_id, "quality": quality, "cost": cost,
                "delivery": delivery, "stability": stability, "total": total,
                "reasons": reasons, "model": "rule", "score_id": row.id}

    # ---------------- 销量预测 / 缺货预警 ----------------
    def forecast(self, product_id: int) -> dict:
        p = self._product(product_id)
        # 12 周用于训练与滚动回测；旧版仅看 4 周，极易被促销/断货周误导。
        dims = p["attrs"] or {}
        rows = self._daily_sales(product_id, days=84,
                                 platform=str(dims.get("platform") or ""),
                                 country=str(dims.get("country") or ""))
        buckets = [0.0] * 12  # 最旧 -> 最新
        now = datetime.utcnow()
        for item in rows:
            day = datetime.strptime(str(item["date"]), "%Y-%m-%d")
            week = min(11, max(0, 11 - int((now - day).days // 7)))
            buckets[week] += float(item["qty"] or 0)

        nonzero = sum(v > 0 for v in buckets)
        def predict(history, model="auto"):
            if not history or sum(history) == 0:
                return 0.0, "cold_start"
            if model == "last_week":
                return history[-1], model
            if model == "mean_12w":
                return sum(history) / len(history), model
            if model == "intermittent" or (model == "auto" and sum(v > 0 for v in history) / len(history) < 0.5):
                nz = [v for v in history if v > 0]
                return sum(nz) / len(nz) * (len(nz) / len(history)), "intermittent"
            recent = history[-4:]
            weights = list(range(1, len(recent) + 1))
            return sum(v * w for v, w in zip(recent, weights)) / sum(weights), "weighted_moving_average"

        # 同一时间窗口比较所有基线，按 WAPE、绝对 Bias 排序自动选择。
        model_names = ["last_week", "mean_12w", "intermittent", "weighted_moving_average"]
        evaluations = []
        for model_name in model_names:
            model_errors, model_signed, model_actual = [], [], 0.0
            for idx in range(max(4, len(buckets) - 4), len(buckets)):
                pred, _ = predict(buckets[:idx], model_name)
                actual = buckets[idx]
                model_errors.append(abs(actual - pred)); model_signed.append(pred - actual)
                model_actual += actual
            model_wape = sum(model_errors) / model_actual if model_actual > 0 else None
            model_bias = sum(model_signed) / model_actual if model_actual > 0 else None
            evaluations.append({"model": model_name, "wape": model_wape, "bias": model_bias,
                                "errors": model_errors, "signed": model_signed})
        ranked = [e for e in evaluations if e["wape"] is not None]
        best = min(ranked, key=lambda e: (e["wape"], abs(e["bias"] or 0))) if ranked else evaluations[1]
        method = best["model"]
        errors, signed_errors = best["errors"], best["signed"]
        actual_total = sum(buckets[-4:])
        raw_forecast, _ = predict(buckets, method)
        # 已明确记录的促销和缺货只作为保守校正；没有事实数据时不猜测。
        if bool(dims.get("promotion_active")):
            raw_forecast *= float(dims.get("promotion_multiplier") or 1.10)
        if int(dims.get("stockout_weeks") or 0) > 0:
            raw_forecast *= min(1.30, 1 + 0.05 * int(dims.get("stockout_weeks") or 0))
        weekly_demand = round(max(0.0, raw_forecast), 1)
        wape = (sum(errors) / actual_total) if actual_total > 0 else None
        bias = (sum(signed_errors) / actual_total) if actual_total > 0 else None
        residual_sigma = math.sqrt(sum(e * e for e in signed_errors) / len(signed_errors)) if signed_errors else 0
        lower = max(0.0, weekly_demand - 1.64 * residual_sigma)
        upper = weekly_demand + 1.64 * residual_sigma
        if nonzero < 4:
            confidence, reason = "low", "有效销售周少于4周，仅可作冷启动参考"
        elif wape is None:
            confidence, reason = "low", "回测期无销量，无法计算误差"
        elif wape <= 0.30 and abs(bias or 0) <= 0.20:
            confidence, reason = "high", "滚动回测 WAPE≤30% 且绝对偏差≤20%"
        elif wape <= 0.50:
            confidence, reason = "medium", "滚动回测 WAPE≤50%，建议人工复核促销和断货"
        else:
            confidence, reason = "low", "滚动回测误差较高，不应自动采购"
        onhand = float((p["attrs"] or {}).get("onhand") or 0)
        risk = "high" if onhand < weekly_demand else ("mid" if onhand < weekly_demand * 2 else "low")
        candidates = [{"model": e["model"],
                       "forecast": round(max(0, predict(buckets, e["model"])[0]), 1),
                       "wape": round(e["wape"], 4) if e["wape"] is not None else None,
                       "bias": round(e["bias"], 4) if e["bias"] is not None else None}
                      for e in evaluations]
        features = {"sale_price": float((p["attrs"] or {}).get("sale_price") or 0),
                    "promotion_active": bool((p["attrs"] or {}).get("promotion_active")),
                    "stockout_weeks": int((p["attrs"] or {}).get("stockout_weeks") or 0),
                    "calendar_month": now.month, "calendar_week": int(now.strftime("%W")),
                    "platform": str((p["attrs"] or {}).get("platform") or "unknown")}
        snapshot = ForecastSnapshot(
            tenant_id=self.tenant_id, product_id=product_id, version="demand-v2.0",
            training_cutoff=now, target_start=now, target_end=now + timedelta(days=7),
            dimensions={"sku": p["sku"], "platform": features["platform"],
                        "country": str((p["attrs"] or {}).get("country") or "unknown")},
            features=features, candidates=candidates, selected_model=method,
            point_forecast=weekly_demand, lower_bound=round(lower, 1), upper_bound=round(upper, 1),
            wape=round(wape, 4) if wape is not None else None,
            bias=round(bias, 4) if bias is not None else None, confidence=confidence)
        # 写路径（新建预测快照）：§18.3 第 3 步（Action 层）欠账，见 D41。
        self.db.add(snapshot); self.db.commit()
        # 自动采购使用租户级门禁，而非单个 SKU 在短窗口内看似良好的结果。
        # 门禁还要求足量真实订单、整体 WAPE/Bias 和覆盖率均达标。
        from ..services.commercial_analytics import forecast_monitoring
        commercial_gate = forecast_monitoring(self.db, self.tenant_id)["commercial_gate"]
        return {"product_id": product_id, "title": p["title"],
                "weekly_demand": weekly_demand, "onhand": onhand, "shortage_risk": risk,
                "suggest_restock_qty": max(0, int(round(weekly_demand * 4 - onhand))),
                "trend": [{"week": f"W{i+1}", "demand": buckets[i]} for i in range(12)],
                "forecast": {"method": method, "horizon_weeks": 1,
                             "point": weekly_demand, "p90_lower": round(lower, 1),
                             "p90_upper": round(upper, 1)},
                "backtest": {"windows": len(errors),
                             "wape": round(wape, 4) if wape is not None else None,
                             "bias": round(bias, 4) if bias is not None else None},
                "data_quality": {"history_weeks": 12, "nonzero_weeks": nonzero,
                                 "confidence": confidence, "reason": reason},
                "automation_allowed": confidence == "high" and commercial_gate["passed"],
                "commercial_gate": commercial_gate,
                "snapshot_id": snapshot.id, "version": snapshot.version,
                "training_cutoff": snapshot.training_cutoff.isoformat() + "Z",
                "features": features, "candidates": candidates}

    def forecast_batch(self, params: dict | None = None, context: dict | None = None) -> dict:
        params, context = params or {}, context or {}
        ids = params.get("product_ids") or context.get("product_ids")
        if not ids:
            got = self.tool("product").call("get_product_ids", status="active", limit=300)
            ids = got.data if got.ok and isinstance(got.data, list) else []
        forecasts, shortages = [], []
        for pid in ids[:300]:
            try:
                f = self.forecast(int(pid))
            except Exception:
                continue
            forecasts.append(f)
            if f["shortage_risk"] != "low":
                shortages.append({k: f[k] for k in
                                  ("product_id", "title", "weekly_demand", "onhand",
                                   "shortage_risk", "suggest_restock_qty")})
        return {"forecasts": forecasts,
                "context_patch": {"shortages": shortages}}
