"""BI 商业智能路由：企业驾驶舱 / 利润分析 / AI 经营报告（第十五章）。"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..ai.llm import ModelRouter
from ..auth import get_current_user
from ..db import get_db
from ..models import Conversation, Listing, Order, Product, User, WorkflowRun
from ..serialize import to_dict
from ..services.commercial_analytics import forecast_monitoring, metric_summary, quality_report
from ..workflows.kinds import LEGACY_AUTOMATION

router = APIRouter(prefix="/bi", tags=["bi"])


@router.get("/metrics")
def commercial_metrics(days: int = 30, include_demo: bool = False,
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return metric_summary(db, user.tenant_id, max(7, min(365, days)), not include_demo)


@router.get("/data-quality")
def data_quality(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return quality_report(db, user.tenant_id)


@router.get("/forecast-monitoring")
def forecasts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return forecast_monitoring(db, user.tenant_id)


@router.get("/forecast-outcomes")
def forecast_outcomes(refresh: bool = True, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    from ..models import ForecastOutcome
    from ..services.outcome_attribution import reconcile_forecast_outcomes
    if refresh:
        result = reconcile_forecast_outcomes(db, user.tenant_id)
        result["items"] = [to_dict(x) for x in result["items"]]
        return result
    rows = db.query(ForecastOutcome).filter(
        ForecastOutcome.tenant_id == user.tenant_id).all()
    actual = sum(x.actual_qty for x in rows)
    return {"evaluated": len(rows), "pending": None,
            "wape": round(sum(x.absolute_error for x in rows) / actual, 4) if actual else None,
            "bias": round(sum(x.forecast_qty - x.actual_qty for x in rows) / actual, 4)
            if actual else None,
            "coverage": round(sum(x.covered for x in rows) / len(rows), 4) if rows else None,
            "items": [to_dict(x) for x in rows]}


@router.get("/dashboard")
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tid = user.tenant_id
    metrics = metric_summary(db, tid, 30, True)

    active_listings = db.query(func.count(Listing.id)).filter(
        Listing.tenant_id == tid, Listing.status == "published").scalar() or 0
    open_convs = db.query(func.count(Conversation.id)).filter(
        Conversation.tenant_id == tid, Conversation.status == "open").scalar() or 0

    sales_trend = []
    for i in range(29, -1, -1):
        start = (datetime.utcnow() - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        daily = metric_summary(db, tid, 1, True, start_at=start,
                               end_at=start + timedelta(days=1))
        sales_trend.append({"date": start.strftime("%Y-%m-%d"), "gmv": daily["gmv"],
                            "orders": daily["orders"]})

    products = db.query(Product).filter(Product.tenant_id == tid).all()
    category_dist = []
    for category in sorted({p.category or "未分类" for p in products}):
        ids = [p.id for p in products if (p.category or "未分类") == category]
        value = metric_summary(db, tid, 30, True, product_ids=ids)["net_revenue"]
        category_dist.append({"category": category, "revenue": value})
    product_sales = []
    for product in products:
        pm = metric_summary(db, tid, 30, True, product_ids=[product.id])
        units = (db.query(func.sum(Order.qty)).filter(
            Order.tenant_id == tid, Order.product_id == product.id,
            Order.created_at >= datetime.utcnow() - timedelta(days=30),
            Order.source.in_(("api", "import", "manual"))).scalar() or 0)
        product_sales.append({"product_id": product.id, "title": product.title,
                              "units": int(units), "revenue": pm["net_revenue"]})
    product_sales.sort(key=lambda x: x["revenue"], reverse=True)
    runs = (db.query(WorkflowRun).filter(WorkflowRun.tenant_id == tid,
                                               WorkflowRun.flow_kind == LEGACY_AUTOMATION)
            .order_by(WorkflowRun.created_at.desc()).limit(5).all())

    return {
        "gmv": metrics["gmv"], "orders": metrics["orders"],
        "profit": metrics["contribution_profit"],
        "contribution_profit": metrics["contribution_profit"],
        "net_revenue": metrics["net_revenue"],
        "ad_spend": metrics["ad_spend"], "roi": metrics["roi"],
        "refund_rate": metrics["refund_rate"],
        "active_listings": active_listings, "open_conversations": open_convs,
        "sales_trend": sales_trend,
        "category_dist": category_dist,
        "platform_dist": [],
        "top_products": product_sales[:5],
        "metric_scope": metrics["scope"], "currency": metrics["currency"],
        "recent_runs": [to_dict(r) for r in runs],
    }


@router.get("/profit")
def profit_analysis(days: int = 30, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    days = max(7, min(90, days))
    tid = user.tenant_id
    series = []
    for i in range(days - 1, -1, -1):
        start = (datetime.utcnow() - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        m = metric_summary(db, tid, 1, True, start_at=start, end_at=start + timedelta(days=1))
        cost = m["order_cost"] + m["order_fees"] + m["ad_spend"]
        series.append({"date": start.strftime("%Y-%m-%d"), "revenue": m["net_revenue"],
                       "cost": round(cost, 2), "profit": m["contribution_profit"],
                       "margin": m["contribution_margin"] or 0})
    revenue = sum(s["revenue"] for s in series)
    cost = sum(s["cost"] for s in series)
    profit = sum(s["profit"] for s in series)
    products = db.query(Product).filter(Product.tenant_id == tid).all()
    categories = []
    for category in sorted({p.category or "未分类" for p in products}):
        ids = [p.id for p in products if (p.category or "未分类") == category]
        value = metric_summary(db, tid, days, True, product_ids=ids)["contribution_profit"]
        categories.append({"category": category, "profit": value})
    return {"days": days, "series": series,
            "summary": {"revenue": round(revenue, 2), "cost": round(cost, 2),
                        "profit": round(profit, 2),
                        "margin": round(profit / revenue, 4) if revenue else 0},
            "by_category": categories, "scope": "real_only", "currency": "USD"}


@router.get("/report")
def ai_report(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """AI 经营报告：KPI 组装后交给 LLM 撰写，离线时用模板文案。"""
    tid = user.tenant_id
    metrics = metric_summary(db, tid, 30, True)
    gmv, orders, profit = metrics["gmv"], metrics["orders"], metrics["contribution_profit"]
    spend, roi = metrics["ad_spend"], metrics["roi"] or 0
    since = datetime.utcnow() - timedelta(days=30)
    top = (db.query(Product.title, func.sum(Order.qty))
           .join(Product, Product.id == Order.product_id)
           .filter(Order.tenant_id == tid, Order.created_at >= since,
                   Order.source.in_(("api", "import", "manual")))
           .group_by(Product.title).order_by(func.sum(Order.qty).desc()).limit(5).all())
    kpis = (f"近30天真实数据口径: GMV=${gmv:.2f}, 净收入=${metrics['net_revenue']:.2f}, "
            f"订单{orders}单, 贡献利润${profit:.2f}, "
            f"广告花费${spend:.2f}, 广告ROI={roi}, "
            f"热销TOP5: {'; '.join(f'{t}({int(n)}件)' for t, n in top)}")

    def fallback_text() -> str:
        lines = [f"# AI 经营报告（{datetime.utcnow().strftime('%Y-%m-%d')}）", "",
                 f"## 核心指标（{kpis}）", "",
                 "## 经营解读",
                 f"- 本期 GMV ${gmv:.2f}，真实利润 ${profit:.2f}，利润率 "
                 f"{(profit / gmv * 100 if gmv else 0):.1f}%。",
                 f"- 广告投放 ROI 为 {roi}，" +
                 ("投放效率优秀，可考虑扩大预算。" if roi > 2 else
                  "投放效率健康，建议持续监控。" if roi > 0.8 else "投放效率偏低，建议优化选词与落地页。"),
                 f"- 热销商品集中在：{'、'.join(t for t, _ in top) or '暂无数据'}，建议围绕该类目加深选品。",
                 "", "## 下一步建议",
                 "- 运行「AI工作流-自动铺货」扩充在售商品池；",
                 "- 对利润率低于 15% 的商品执行「动态定价」；",
                 "- 关注「补货预警」，避免热销品断货。"]
        return "\n".join(lines)

    router_llm = ModelRouter(db)
    report_text = fallback_text()
    if router_llm.available:
        try:
            r = router_llm.chat([
                {"role": "system",
                 "content": "你是资深跨境电商运营顾问，用中文 Markdown 撰写简洁的经营分析报告。"},
                {"role": "user", "content": f"请基于以下 KPI 撰写经营报告（含指标解读+3条行动建议）：\n{kpis}"},
            ])
            if r["content"]:
                report_text = r["content"]
        except Exception:
            pass
    return {"report": report_text,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}
