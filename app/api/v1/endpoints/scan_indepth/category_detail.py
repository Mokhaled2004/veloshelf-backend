"""GET /scan/category?id=<category_name> — full category analytics dashboard."""

from fastapi import Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.scan_indepth.router import router


def _suggestions(osa_pct: float, oos_sku_count: int, total_skus: int,
                 total_stores: int, top_country: str | None, worst_channel: str | None) -> list[str]:
    tips: list[str] = []

    if osa_pct < 40:
        tips.append(
            f"Category OSA is critically low at {osa_pct:.1f}% — well below the 65% target. "
            "Trigger an emergency replenishment review across all associated stores immediately."
        )
    elif osa_pct < 55:
        tips.append(
            f"Category OSA stands at {osa_pct:.1f}%, which is below acceptable range. "
            "Prioritise restocking the lowest-performing SKUs within the next 48 hours."
        )
    elif osa_pct < 65:
        tips.append(
            f"Category OSA is at {osa_pct:.1f}% — approaching target but not yet there. "
            "Audit category shelf space and identify gaps in replenishment frequency."
        )
    else:
        tips.append(
            f"Category OSA is healthy at {osa_pct:.1f}%. "
            "Maintain current replenishment cadence and monitor for seasonal demand shifts."
        )

    if total_skus > 0:
        oos_pct = oos_sku_count / total_skus * 100
        if oos_pct > 40:
            tips.append(
                f"{oos_sku_count} of {total_skus} SKUs ({oos_pct:.0f}%) show high OOS exposure. "
                "Consider range rationalisation and removing low-velocity SKUs."
            )
        elif oos_sku_count > 0:
            tips.append(
                f"{oos_sku_count} SKU(s) are performing below 50% OSA — "
                "include them in the next targeted replenishment route."
            )

    if worst_channel:
        tips.append(
            f"Channel '{worst_channel}' shows the weakest category performance. "
            "Review distributor delivery schedules and shelf-space allocation for this channel."
        )

    if top_country:
        tips.append(
            f"Country '{top_country}' leads category availability. "
            "Use its replenishment model as a benchmark for underperforming markets."
        )

    if total_stores > 0 and osa_pct < 65:
        tips.append(
            f"Across {total_stores} scanned stores, there is a significant coverage gap. "
            "Assign field reps to conduct compliance audits at the lowest-scoring locations."
        )

    return tips


@router.get("/category")
def get_category_detail(
    id: str = Query(..., description="category_name"),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    cat_name = id.strip()

    # Also try fuzzy match in case the category comes in from autocomplete with slight variance
    cat_row = db.execute(
        text(
            "SELECT category_name, nestle_category FROM dim_category "
            "WHERE category_name = :cat OR category_name ILIKE :cat_like LIMIT 1"
        ),
        {"cat": cat_name, "cat_like": cat_name},
    ).fetchone()

    # Fallback: check fact_osa_checks directly
    if not cat_row:
        fact_cat = db.execute(
            text(
                "SELECT DISTINCT category_name FROM fact_osa_checks "
                "WHERE osa_type='IR OSA' AND category_name ILIKE :cat LIMIT 1"
            ),
            {"cat": cat_name},
        ).fetchone()
        if not fact_cat:
            raise HTTPException(status_code=404, detail=f"Category '{cat_name}' not found.")
        cat_name = fact_cat[0]
        nestle = db.execute(
            text("SELECT nestle_category FROM dim_category WHERE category_name = :c LIMIT 1"),
            {"c": cat_name},
        ).scalar()
        meta = {"category": cat_name, "nestle_category": str(nestle or "").strip()}
    else:
        cat_name = cat_row[0]
        meta = {"category": cat_row[0], "nestle_category": cat_row[1] or ""}

    scope_clause = ""
    scope_params: dict = {"cat": cat_name}
    if not ctx.is_unrestricted and ctx.countries:
        scope_clause = "AND country_name = ANY(:scope_countries)"
        scope_params["scope_countries"] = ctx.countries

    # ── Summary KPIs — use agg_osa_by_category (has category_name as primary dim) ──
    # agg_osa_by_sku has sap_code as primary — use it for SKU count
    kpi_cat = db.execute(
        text(
            f"SELECT SUM(total_checks), SUM(available_checks) "
            f"FROM agg_osa_by_category "
            f"WHERE category_name = :cat {scope_clause}"
        ),
        scope_params,
    ).fetchone()
    total_checks = int(kpi_cat[0] or 0)
    avail_checks = int(kpi_cat[1] or 0)

    # Fallback to fact if agg is empty
    if total_checks == 0:
        kpi_fact = db.execute(
            text(
                f"SELECT COUNT(*), SUM(osa_flag) FROM fact_osa_checks "
                f"WHERE osa_type='IR OSA' AND category_name = :cat {scope_clause}"
            ),
            scope_params,
        ).fetchone()
        total_checks = int(kpi_fact[0] or 0)
        avail_checks = int(kpi_fact[1] or 0)

    osa_pct  = round(avail_checks / total_checks * 100, 2) if total_checks else 0.0
    oos_rate = round((total_checks - avail_checks) / total_checks * 100, 2) if total_checks else 0.0

    # SKU + store counts from fact table (agg_osa_by_sku has no store_code)
    counts = db.execute(
        text(
            f"SELECT COUNT(DISTINCT sap_code), COUNT(DISTINCT store_code) "
            f"FROM fact_osa_checks "
            f"WHERE osa_type='IR OSA' AND category_name = :cat {scope_clause}"
        ),
        scope_params,
    ).fetchone()
    total_skus   = int(counts[0] or 0)
    total_stores = int(counts[1] or 0)

    # ── Top 8 SKUs ───────────────────────────────────────────────────────────
    top_sku_rows = db.execute(
        text(
            f"SELECT sap_code, sku_name, SUM(total_checks), SUM(available_checks) "
            f"FROM agg_osa_by_sku "
            f"WHERE category_name = :cat {scope_clause} AND sap_code <> '' "
            f"GROUP BY sap_code, sku_name HAVING SUM(total_checks) > 0 "
            f"ORDER BY (SUM(available_checks)::float / NULLIF(SUM(total_checks),0)) DESC LIMIT 8"
        ),
        scope_params,
    ).fetchall()
    top_skus = [
        {"sap_code": r[0], "sku_name": r[1] or r[0],
         "osa_pct": round(int(r[3] or 0) / int(r[2]) * 100, 2) if int(r[2] or 0) else 0.0,
         "total": int(r[2] or 0)}
        for r in top_sku_rows
    ]

    # ── Bottom 8 SKUs ────────────────────────────────────────────────────────
    bot_sku_rows = db.execute(
        text(
            f"SELECT sap_code, sku_name, SUM(total_checks), SUM(available_checks) "
            f"FROM agg_osa_by_sku "
            f"WHERE category_name = :cat {scope_clause} AND sap_code <> '' "
            f"GROUP BY sap_code, sku_name HAVING SUM(total_checks) > 0 "
            f"ORDER BY (SUM(available_checks)::float / NULLIF(SUM(total_checks),0)) ASC LIMIT 8"
        ),
        scope_params,
    ).fetchall()
    bottom_skus = [
        {"sap_code": r[0], "sku_name": r[1] or r[0],
         "osa_pct": round(int(r[3] or 0) / int(r[2]) * 100, 2) if int(r[2] or 0) else 0.0,
         "total": int(r[2] or 0)}
        for r in bot_sku_rows
    ]
    oos_sku_count = sum(1 for s in bottom_skus if s["osa_pct"] < 50)

    # ── By country ───────────────────────────────────────────────────────────
    country_rows = db.execute(
        text(
            f"SELECT country_name, SUM(total_checks), SUM(available_checks) "
            f"FROM agg_osa_by_category "
            f"WHERE category_name = :cat {scope_clause} AND country_name <> '' "
            f"GROUP BY country_name ORDER BY country_name"
        ),
        scope_params,
    ).fetchall()
    # Fallback to fact
    if not country_rows:
        country_rows = db.execute(
            text(
                f"SELECT country_name, COUNT(*), SUM(osa_flag) FROM fact_osa_checks "
                f"WHERE osa_type='IR OSA' AND category_name = :cat {scope_clause} AND country_name IS NOT NULL "
                f"GROUP BY country_name ORDER BY country_name"
            ),
            scope_params,
        ).fetchall()
    by_country = [
        {"country": r[0],
         "osa_pct": round(int(r[2] or 0) / int(r[1]) * 100, 2) if int(r[1] or 0) else 0.0,
         "total": int(r[1] or 0)}
        for r in country_rows
    ]
    top_country = max(by_country, key=lambda x: x["osa_pct"])["country"] if by_country else None

    # ── By channel ───────────────────────────────────────────────────────────
    channel_rows = db.execute(
        text(
            f"SELECT channel_name, SUM(total_checks), SUM(available_checks) "
            f"FROM agg_osa_by_category "
            f"WHERE category_name = :cat {scope_clause} AND channel_name <> '' "
            f"GROUP BY channel_name ORDER BY channel_name"
        ),
        scope_params,
    ).fetchall()
    if not channel_rows:
        channel_rows = db.execute(
            text(
                f"SELECT channel_name, COUNT(*), SUM(osa_flag) FROM fact_osa_checks "
                f"WHERE osa_type='IR OSA' AND category_name = :cat {scope_clause} AND channel_name IS NOT NULL "
                f"GROUP BY channel_name ORDER BY channel_name"
            ),
            scope_params,
        ).fetchall()
    by_channel = [
        {"channel": r[0],
         "osa_pct": round(int(r[2] or 0) / int(r[1]) * 100, 2) if int(r[1] or 0) else 0.0,
         "total": int(r[1] or 0)}
        for r in channel_rows
    ]
    worst_channel = min(by_channel, key=lambda x: x["osa_pct"])["channel"] if by_channel else None

    # ── Weekly trend ─────────────────────────────────────────────────────────
    trend_rows = db.execute(
        text(
            f"SELECT week_label, week_number, year, COUNT(*), SUM(osa_flag) "
            f"FROM fact_osa_checks "
            f"WHERE category_name = :cat AND osa_type='IR OSA' {scope_clause} "
            f"GROUP BY week_label, week_number, year "
            f"ORDER BY year DESC, week_number DESC LIMIT 8"
        ),
        scope_params,
    ).fetchall()
    trend = [
        {"week": r[0] or f"W{r[1]}",
         "osa_pct": round(int(r[4] or 0) / int(r[3]) * 100, 2) if int(r[3] or 0) else 0.0}
        for r in reversed(trend_rows)
    ]

    # ── POG ──────────────────────────────────────────────────────────────────
    pog_row = db.execute(
        text(
            "SELECT AVG(pog_compliance_pct), AVG(osa_pct), AVG(facings_pct), "
            "       AVG(product_placement_pct), AVG(assortment_pct) "
            "FROM fact_pog_compliance_category WHERE category_name = :cat"
        ),
        {"cat": cat_name},
    ).fetchone()
    pog = {
        "pog_compliance_pct":    round(float(pog_row[0] or 0), 2) if pog_row and pog_row[0] else None,
        "osa_pct":               round(float(pog_row[1] or 0), 2) if pog_row and pog_row[1] else None,
        "facings_pct":           round(float(pog_row[2] or 0), 2) if pog_row and pog_row[2] else None,
        "product_placement_pct": round(float(pog_row[3] or 0), 2) if pog_row and pog_row[3] else None,
        "assortment_pct":        round(float(pog_row[4] or 0), 2) if pog_row and pog_row[4] else None,
    } if pog_row else None

    result = {
        "meta": meta,
        "kpi": {"osa_pct": osa_pct, "oos_rate": oos_rate, "total_checks": total_checks,
                "total_skus": total_skus, "total_stores": total_stores},
        "top_skus": top_skus, "bottom_skus": bottom_skus,
        "by_country": by_country, "by_channel": by_channel,
        "trend": trend, "pog": pog,
        "suggestions": _suggestions(osa_pct, oos_sku_count, total_skus, total_stores, top_country, worst_channel),
    }
    set_cached(cache_key, result, ttl=900)
    return result
