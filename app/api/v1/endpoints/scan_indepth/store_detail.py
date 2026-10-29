"""GET /scan/store?id=<store_code> — full store analytics dashboard."""

from fastapi import Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.scan_indepth.router import router


def _suggestions(osa_pct: float, oos_sku_count: int, total_skus: int,
                 worst_category: str | None, last_scan: str | None) -> list[str]:
    tips: list[str] = []

    if osa_pct < 40:
        tips.append(
            f"Store OSA is critically low at {osa_pct:.1f}%. "
            "Immediate restock visit is required — escalate to the area manager today."
        )
    elif osa_pct < 55:
        tips.append(
            f"Store OSA is at {osa_pct:.1f}%, significantly below the 65% target. "
            "Schedule a replenishment visit within 24 hours."
        )
    elif osa_pct < 65:
        tips.append(
            f"Store OSA is at {osa_pct:.1f}% — close to target but not yet compliant. "
            "Identify the top 3 OOS SKUs below and include them in the next delivery."
        )
    else:
        tips.append(
            f"Store OSA is healthy at {osa_pct:.1f}%. "
            "Maintain the current replenishment schedule and verify shelf facings on next visit."
        )

    if total_skus > 0:
        oos_pct = oos_sku_count / total_skus * 100 if total_skus else 0
        if oos_sku_count > 10:
            tips.append(
                f"{oos_sku_count} SKUs ({oos_pct:.0f}% of the range) are completely out of stock. "
                "Review the full order list and align with the store manager on shelf space."
            )
        elif oos_sku_count > 0:
            tips.append(
                f"{oos_sku_count} SKU(s) have zero OSA — include them in the next delivery route."
            )

    if worst_category:
        tips.append(
            f"Category '{worst_category}' has the lowest OSA in this store. "
            "Prioritise shelf replenishment for this category on the next visit."
        )

    if last_scan:
        tips.append(
            f"Last scan recorded on {last_scan}. "
            "Ensure weekly scan frequency is maintained for accurate inventory visibility."
        )

    if osa_pct >= 65 and oos_sku_count == 0:
        tips.append(
            "No OOS SKUs detected. The store is fully compliant — "
            "focus next visit on facing count verification and planogram adherence."
        )

    return tips


@router.get("/store")
def get_store_detail(
    id: str = Query(..., description="store_code or store_name"),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    store_id = id.strip()

    # Resolve meta — accept store_code OR store_name
    store_row = db.execute(
        text(
            "SELECT store_code, store_name FROM dim_store "
            "WHERE store_code = :sc OR store_name ILIKE :sn LIMIT 1"
        ),
        {"sc": store_id, "sn": store_id},
    ).fetchone()

    # Fallback: look in fact_osa_checks
    if not store_row:
        fact_store = db.execute(
            text(
                "SELECT store_code, store_name FROM fact_osa_checks "
                "WHERE osa_type='IR OSA' "
                "  AND (store_code = :sc OR store_name ILIKE :sn) LIMIT 1"
            ),
            {"sc": store_id, "sn": store_id},
        ).fetchone()
        if not fact_store:
            raise HTTPException(status_code=404, detail=f"Store '{store_id}' not found.")
        store_code = str(fact_store[0] or store_id).strip()
        meta = {"store_code": store_code, "store_name": str(fact_store[1] or store_code).strip()}
    else:
        store_code = str(store_row[0]).strip()
        meta = {"store_code": store_code, "store_name": str(store_row[1] or store_code).strip()}

    if not ctx.is_unrestricted and ctx.stores and store_code not in ctx.stores:
        raise HTTPException(status_code=403, detail="Access to this store is not permitted.")

    cache_key = build_key("scan_store_v2", store_code=store_code)
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    params: dict = {"sc": store_code}

    # ── Summary KPIs from agg_osa_by_store ───────────────────────────────────
    # agg_osa_by_store has: store_code, store_name, country_name, channel_name,
    #                       customer_name, category_name, display_type,
    #                       total_checks, available_checks
    # NO sap_code or sku_name — those need fact table
    kpi = db.execute(
        text(
            "SELECT SUM(total_checks), SUM(available_checks), "
            "       COUNT(DISTINCT category_name) "
            "FROM agg_osa_by_store WHERE store_code = :sc"
        ),
        params,
    ).fetchone()
    total_checks = int(kpi[0] or 0)
    avail_checks = int(kpi[1] or 0)
    total_cats   = int(kpi[2] or 0)

    # Fallback to fact if agg empty
    if total_checks == 0:
        kpi_fact = db.execute(
            text(
                "SELECT COUNT(*), SUM(osa_flag), COUNT(DISTINCT category_name) "
                "FROM fact_osa_checks WHERE store_code = :sc AND osa_type='IR OSA'"
            ),
            params,
        ).fetchone()
        total_checks = int(kpi_fact[0] or 0)
        avail_checks = int(kpi_fact[1] or 0)
        total_cats   = int(kpi_fact[2] or 0)

    osa_pct  = round(avail_checks / total_checks * 100, 2) if total_checks else 0.0
    oos_rate = round((total_checks - avail_checks) / total_checks * 100, 2) if total_checks else 0.0

    # SKU count from fact (agg has no sap_code)
    sku_count = db.execute(
        text("SELECT COUNT(DISTINCT sap_code) FROM fact_osa_checks WHERE store_code = :sc AND osa_type='IR OSA'"),
        params,
    ).scalar()
    total_skus = int(sku_count or 0)

    # ── By category (from agg_osa_by_store) ──────────────────────────────────
    cat_rows = db.execute(
        text(
            "SELECT category_name, SUM(total_checks), SUM(available_checks) "
            "FROM agg_osa_by_store "
            "WHERE store_code = :sc AND category_name <> '' "
            "GROUP BY category_name ORDER BY category_name"
        ),
        params,
    ).fetchall()
    if not cat_rows:
        cat_rows = db.execute(
            text(
                "SELECT category_name, COUNT(*), SUM(osa_flag) FROM fact_osa_checks "
                "WHERE store_code = :sc AND osa_type='IR OSA' AND category_name IS NOT NULL "
                "GROUP BY category_name ORDER BY category_name"
            ),
            params,
        ).fetchall()
    by_category = [
        {"category": r[0],
         "osa_pct": round(int(r[2] or 0) / int(r[1]) * 100, 2) if int(r[1] or 0) else 0.0,
         "total": int(r[1] or 0)}
        for r in cat_rows
    ]
    worst_category = min(by_category, key=lambda x: x["osa_pct"])["category"] if by_category else None

    # ── OOS SKUs — must use fact table ────────────────────────────────────────
    oos_sku_rows = db.execute(
        text(
            "SELECT sap_code, sku_name, category_name, COUNT(*), SUM(osa_flag) "
            "FROM fact_osa_checks "
            "WHERE store_code = :sc AND osa_type='IR OSA' AND sap_code IS NOT NULL "
            "GROUP BY sap_code, sku_name, category_name HAVING COUNT(*) > 0 "
            "ORDER BY (SUM(osa_flag)::float / NULLIF(COUNT(*),0)) ASC LIMIT 12"
        ),
        params,
    ).fetchall()
    oos_skus = [
        {"sap_code": r[0], "sku_name": r[1] or r[0], "category": r[2] or "",
         "osa_pct": round(int(r[4] or 0) / int(r[3]) * 100, 2) if int(r[3] or 0) else 0.0,
         "total": int(r[3] or 0)}
        for r in oos_sku_rows
    ]
    oos_sku_count = sum(1 for s in oos_skus if s["osa_pct"] == 0)

    # ── Weekly trend ─────────────────────────────────────────────────────────
    trend_rows = db.execute(
        text(
            "SELECT week_label, week_number, year, COUNT(*), SUM(osa_flag) "
            "FROM fact_osa_checks "
            "WHERE store_code = :sc AND osa_type='IR OSA' "
            "GROUP BY week_label, week_number, year "
            "ORDER BY year DESC, week_number DESC LIMIT 8"
        ),
        params,
    ).fetchall()
    trend = [
        {"week": r[0] or f"W{r[1]}",
         "osa_pct": round(int(r[4] or 0) / int(r[3]) * 100, 2) if int(r[3] or 0) else 0.0}
        for r in reversed(trend_rows)
    ]

    # ── POG ──────────────────────────────────────────────────────────────────
    pog_row = db.execute(
        text(
            "SELECT pog_compliance_pct, osa_pct, facings_pct, "
            "       product_placement_pct, assortment_pct "
            "FROM fact_pog_compliance_store WHERE store_name ILIKE :sn LIMIT 1"
        ),
        {"sn": meta["store_name"]},
    ).fetchone()
    pog = {
        "pog_compliance_pct":    round(float(pog_row[0] or 0), 2),
        "osa_pct":               round(float(pog_row[1] or 0), 2),
        "facings_pct":           round(float(pog_row[2] or 0), 2),
        "product_placement_pct": round(float(pog_row[3] or 0), 2),
        "assortment_pct":        round(float(pog_row[4] or 0), 2),
    } if pog_row else None

    # ── Last scan ─────────────────────────────────────────────────────────────
    last_scan = db.execute(
        text("SELECT MAX(submit_date) FROM fact_osa_checks WHERE store_code = :sc AND osa_type='IR OSA'"),
        params,
    ).scalar()
    last_scan_str = str(last_scan) if last_scan else None

    result = {
        "meta": meta, "last_scan": last_scan_str,
        "kpi": {"osa_pct": osa_pct, "oos_rate": oos_rate, "total_checks": total_checks,
                "total_skus": total_skus, "total_cats": total_cats},
        "by_category": by_category, "oos_skus": oos_skus, "trend": trend, "pog": pog,
        "suggestions": _suggestions(osa_pct, oos_sku_count, total_skus, worst_category, last_scan_str),
    }
    set_cached(cache_key, result, ttl=900)
    return result
