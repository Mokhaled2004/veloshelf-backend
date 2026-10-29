"""GET /scan/sku?id=<sap_code or sku_name> — full SKU analytics dashboard."""

import re
from fastapi import Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.scan_indepth.router import router


def _clean(val) -> str:
    """Normalise sap_code: strip whitespace and trailing .0"""
    s = str(val or "").strip()
    if re.fullmatch(r'\d+\.0', s):
        s = s[:-2]
    return s


def _sap_where(col: str = "sap_code") -> str:
    """
    Match sap_code regardless of whether it's stored as '12518160' or '12518160.0'.
    We generate two variants and match either.
    """
    return (
        f"(REGEXP_REPLACE({col}::text, '\\.0$', '') = :sap "
        f" OR {col}::text = :sap "
        f" OR {col}::text = :sap_float)"
    )


def _suggestions(osa_pct: float, oos_stores: int, total_stores: int) -> list[str]:
    tips: list[str] = []
    oos_rate = (oos_stores / total_stores * 100) if total_stores else 0

    if osa_pct < 40:
        tips.append(
            f"SKU OSA is critically low at {osa_pct:.1f}%. "
            "This SKU is at high risk of lost sales — initiate emergency replenishment across all {total_stores} stores."
        )
    elif osa_pct < 55:
        tips.append(
            f"SKU OSA is {osa_pct:.1f}%, which is well below the 65% target. "
            "Prioritise restocking in the flagged OOS stores within the next 24 hours."
        )
    elif osa_pct < 65:
        tips.append(
            f"SKU OSA is at {osa_pct:.1f}% — approaching target. "
            "Review replenishment frequency and confirm shelf allocation at the lowest-scoring stores."
        )
    else:
        tips.append(
            f"SKU OSA is healthy at {osa_pct:.1f}% across {total_stores} stores. "
            "Maintain current replenishment cadence and monitor for any downward trend."
        )

    if oos_rate > 30:
        tips.append(
            f"{oos_stores} stores ({oos_rate:.0f}%) are currently out-of-stock. "
            "Assign field reps immediately to conduct emergency shelf restocking."
        )
    elif oos_rate > 10:
        tips.append(
            f"{oos_stores} stores ({oos_rate:.0f}%) report empty shelves for this SKU. "
            "Prioritise these locations in the next replenishment route."
        )
    elif oos_stores > 0:
        tips.append(
            f"{oos_stores} store(s) have low availability — "
            "include them in the upcoming delivery schedule."
        )

    if osa_pct >= 65 and oos_stores == 0:
        tips.append(
            "Full shelf coverage achieved across all scanned stores. "
            "Next step: verify facing counts and planogram compliance on the next field visit."
        )

    return tips


@router.get("/sku")
def get_sku_detail(
    id: str = Query(..., description="sap_code or sku_name"),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    raw_id   = id.strip()
    sap_code = _clean(raw_id)

    # Both forms used in WHERE: '12518160' and '12518160.0'
    sap_float = f"{sap_code}.0"

    cache_key = build_key("scan_sku_v3", sap_code=sap_code, scope_countries=sorted(ctx.countries))
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    # ── 1. Resolve SKU meta ───────────────────────────────────────────────────
    # First try dim_sku
    sku_row = db.execute(
        text(
            "SELECT s.sap_code, s.sku_name, s.barcode, s.category_name, c.nestle_category "
            "FROM dim_sku s "
            "LEFT JOIN dim_category c ON c.category_name = s.category_name "
            f"WHERE ({_sap_where('s.sap_code')}) OR s.sku_name ILIKE :name "
            "LIMIT 1"
        ),
        {"sap": sap_code, "sap_float": sap_float, "name": sap_code},
    ).fetchone()

    if sku_row:
        sap_code  = _clean(sku_row[0])
        sap_float = f"{sap_code}.0"
        meta = {
            "sap_code":        sap_code,
            "sku_name":        str(sku_row[1] or sap_code).strip(),
            "barcode":         str(sku_row[2] or "").strip(),
            "category":        str(sku_row[3] or "").strip(),
            "nestle_category": str(sku_row[4] or "").strip(),
        }
    else:
        # Fallback: fact_osa_checks
        fact_row = db.execute(
            text(
                "SELECT sap_code, sku_name, category_name "
                "FROM fact_osa_checks "
                "WHERE osa_type = 'IR OSA' "
                f"  AND ({_sap_where()} OR sku_name ILIKE :name) "
                "LIMIT 1"
            ),
            {"sap": sap_code, "sap_float": sap_float, "name": sap_code},
        ).fetchone()
        if not fact_row:
            raise HTTPException(status_code=404, detail=f"SKU '{sap_code}' not found in the database.")
        sap_code  = _clean(fact_row[0])
        sap_float = f"{sap_code}.0"
        nestle    = db.execute(
            text("SELECT nestle_category FROM dim_category WHERE category_name = :c LIMIT 1"),
            {"c": fact_row[2]},
        ).scalar()
        meta = {
            "sap_code":        sap_code,
            "sku_name":        str(fact_row[1] or sap_code).strip(),
            "barcode":         "",
            "category":        str(fact_row[2] or "").strip(),
            "nestle_category": str(nestle or "").strip(),
        }

    # ── Shared params ─────────────────────────────────────────────────────────
    scope_clause = ""
    base_params: dict = {"sap": sap_code, "sap_float": sap_float}
    if not ctx.is_unrestricted and ctx.countries:
        scope_clause = "AND country_name = ANY(:scope_countries)"
        base_params["scope_countries"] = ctx.countries

    sap_match = _sap_where()

    # ── 2. Summary KPIs (agg_osa_by_sku first, fallback to fact) ─────────────
    kpi_row = db.execute(
        text(f"SELECT SUM(total_checks), SUM(available_checks) "
             f"FROM agg_osa_by_sku WHERE {sap_match} {scope_clause}"),
        base_params,
    ).fetchone()
    total_checks = int(kpi_row[0] or 0)
    avail_checks = int(kpi_row[1] or 0)

    if total_checks == 0:
        kpi_fact = db.execute(
            text(f"SELECT COUNT(*), SUM(osa_flag) FROM fact_osa_checks "
                 f"WHERE osa_type='IR OSA' AND {sap_match} {scope_clause}"),
            base_params,
        ).fetchone()
        total_checks = int(kpi_fact[0] or 0)
        avail_checks = int(kpi_fact[1] or 0)

    osa_pct  = round(avail_checks / total_checks * 100, 2) if total_checks else 0.0
    oos_rate = round((total_checks - avail_checks) / total_checks * 100, 2) if total_checks else 0.0

    # ── 3. Store counts (fact table — agg_osa_by_store has no sap_code) ───────
    store_kpi = db.execute(
        text(f"SELECT COUNT(DISTINCT store_code), "
             f"       COUNT(DISTINCT CASE WHEN osa_flag = 1 THEN store_code END) "
             f"FROM fact_osa_checks "
             f"WHERE osa_type='IR OSA' AND {sap_match} {scope_clause}"),
        base_params,
    ).fetchone()
    total_stores    = int(store_kpi[0] or 0)
    in_stock_stores = int(store_kpi[1] or 0)
    oos_stores      = total_stores - in_stock_stores

    # ── 4. Weekly trend ───────────────────────────────────────────────────────
    trend_rows = db.execute(
        text(f"SELECT week_label, week_number, year, COUNT(*), SUM(osa_flag) "
             f"FROM fact_osa_checks "
             f"WHERE osa_type='IR OSA' AND {sap_match} {scope_clause} "
             f"GROUP BY week_label, week_number, year "
             f"ORDER BY year DESC, week_number DESC LIMIT 8"),
        base_params,
    ).fetchall()
    trend = [
        {"week": r[0] or f"W{r[1]}",
         "osa_pct": round(int(r[4] or 0) / int(r[3]) * 100, 2) if int(r[3] or 0) else 0.0}
        for r in reversed(trend_rows)
    ]

    # ── 5. By country ─────────────────────────────────────────────────────────
    country_rows = db.execute(
        text(f"SELECT country_name, SUM(total_checks), SUM(available_checks) "
             f"FROM agg_osa_by_sku WHERE {sap_match} {scope_clause} AND country_name <> '' "
             f"GROUP BY country_name ORDER BY country_name"),
        base_params,
    ).fetchall()
    # Fallback to fact if agg empty
    if not country_rows:
        country_rows = db.execute(
            text(f"SELECT country_name, COUNT(*), SUM(osa_flag) "
                 f"FROM fact_osa_checks "
                 f"WHERE osa_type='IR OSA' AND {sap_match} {scope_clause} AND country_name IS NOT NULL "
                 f"GROUP BY country_name ORDER BY country_name"),
            base_params,
        ).fetchall()
    by_country = [
        {"country": r[0], "osa_pct": round(int(r[2] or 0) / int(r[1]) * 100, 2) if int(r[1] or 0) else 0.0, "total": int(r[1] or 0)}
        for r in country_rows
    ]

    # ── 6. By channel ─────────────────────────────────────────────────────────
    channel_rows = db.execute(
        text(f"SELECT channel_name, SUM(total_checks), SUM(available_checks) "
             f"FROM agg_osa_by_sku WHERE {sap_match} {scope_clause} AND channel_name <> '' "
             f"GROUP BY channel_name ORDER BY channel_name"),
        base_params,
    ).fetchall()
    if not channel_rows:
        channel_rows = db.execute(
            text(f"SELECT channel_name, COUNT(*), SUM(osa_flag) "
                 f"FROM fact_osa_checks "
                 f"WHERE osa_type='IR OSA' AND {sap_match} {scope_clause} AND channel_name IS NOT NULL "
                 f"GROUP BY channel_name ORDER BY channel_name"),
            base_params,
        ).fetchall()
    by_channel = [
        {"channel": r[0], "osa_pct": round(int(r[2] or 0) / int(r[1]) * 100, 2) if int(r[1] or 0) else 0.0, "total": int(r[1] or 0)}
        for r in channel_rows
    ]

    # ── 7. OOS stores ─────────────────────────────────────────────────────────
    oos_store_rows = db.execute(
        text(f"SELECT store_code, store_name, country_name, COUNT(*), SUM(osa_flag) "
             f"FROM fact_osa_checks "
             f"WHERE osa_type='IR OSA' AND {sap_match} {scope_clause} AND store_code IS NOT NULL "
             f"GROUP BY store_code, store_name, country_name HAVING COUNT(*) > 0 "
             f"ORDER BY (SUM(osa_flag)::float / NULLIF(COUNT(*),0)) ASC LIMIT 10"),
        base_params,
    ).fetchall()
    oos_store_list = [
        {"store_code": r[0], "store_name": r[1] or "Unknown", "country": r[2] or "",
         "osa_pct": round(int(r[4] or 0) / int(r[3]) * 100, 2) if int(r[3] or 0) else 0.0,
         "total_checks": int(r[3] or 0)}
        for r in oos_store_rows
    ]

    # ── 8. POG ────────────────────────────────────────────────────────────────
    pog_row = db.execute(
        text("SELECT pog_compliance_pct, osa_pct, facings_pct, product_placement_pct, assortment_pct "
             "FROM fact_pog_compliance_sku WHERE sku_name ILIKE :name LIMIT 1"),
        {"name": meta["sku_name"]},
    ).fetchone()
    pog = {
        "pog_compliance_pct": float(pog_row[0] or 0), "osa_pct": float(pog_row[1] or 0),
        "facings_pct": float(pog_row[2] or 0), "product_placement_pct": float(pog_row[3] or 0),
        "assortment_pct": float(pog_row[4] or 0),
    } if pog_row else None

    # ── 9. Last scan ──────────────────────────────────────────────────────────
    last_scan = db.execute(
        text(f"SELECT MAX(submit_date) FROM fact_osa_checks "
             f"WHERE {sap_match} AND osa_type='IR OSA'"),
        {"sap": sap_code, "sap_float": sap_float},
    ).scalar()

    result = {
        "meta": meta, "last_scan": str(last_scan) if last_scan else None,
        "kpi": {
            "osa_pct": osa_pct, "oos_rate": oos_rate,
            "total_checks": total_checks, "avail_checks": avail_checks,
            "total_stores": total_stores, "in_stock_stores": in_stock_stores, "oos_stores": oos_stores,
        },
        "trend": trend, "by_country": by_country, "by_channel": by_channel,
        "oos_stores": oos_store_list, "pog": pog,
        "suggestions": _suggestions(osa_pct, oos_stores, total_stores),
    }
    set_cached(cache_key, result, ttl=900)
    return result
