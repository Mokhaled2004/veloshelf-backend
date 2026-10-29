"""
Aggregate Refresh endpoints — admin-only (tier 1).

GET  /settings/available-weeks
     Distinct (year, week_number, week_label) from all three fact tables,
     merged and sorted newest-first.

POST /settings/refresh-all-aggregates
     Body: { "year": 2026, "week_number": 32 }
     Rebuilds every aggregate table for the 3 sections (OSA / SOS / SOD)
     for the requested week, then flushes the entire Redis cache.

POST /settings/refresh-aggregates          ← kept for backward compat
     Same as above (same body, same logic).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import invalidate_availability

router = APIRouter(prefix="/settings", tags=["Settings"])


class RefreshRequest(BaseModel):
    year:        int
    week_number: int


# ── helpers ──────────────────────────────────────────────────────────────────

def _refresh_osa(db: Session, year: int, week_number: int) -> None:
    """Rebuild all OSA aggregate tables."""
    params = {"year": year, "wk": week_number}

    # filter options — full rebuild (no week dimension)
    db.execute(text("TRUNCATE agg_osa_filter_options"))
    db.execute(text(
        "INSERT INTO agg_osa_filter_options "
        "  (country_name, channel_name, customer_name, display_type) "
        "SELECT DISTINCT "
        "    COALESCE(country_name,''), COALESCE(channel_name,''), "
        "    COALESCE(customer_name,''), COALESCE(display_type,'') "
        "FROM fact_osa_checks WHERE osa_type = 'IR OSA'"
    ))

    # by_store
    db.execute(text(
        "DELETE FROM agg_osa_by_store WHERE store_code IN ("
        "  SELECT DISTINCT COALESCE(store_code,'') FROM fact_osa_checks "
        "  WHERE osa_type='IR OSA' AND year=:year AND week_number=:wk)"
    ), params)
    db.execute(text(
        "INSERT INTO agg_osa_by_store "
        "  (store_code,store_name,country_name,channel_name,customer_name,category_name,display_type,total_checks,available_checks) "
        "SELECT COALESCE(store_code,''),COALESCE(store_name,''),COALESCE(country_name,''),"
        "       COALESCE(channel_name,''),COALESCE(customer_name,''),COALESCE(category_name,''),"
        "       COALESCE(display_type,''),COUNT(*),COALESCE(SUM(osa_flag),0) "
        "FROM fact_osa_checks WHERE osa_type='IR OSA' GROUP BY 1,2,3,4,5,6,7"
    ))

    # by_country
    db.execute(text(
        "DELETE FROM agg_osa_by_country WHERE country_name IN ("
        "  SELECT DISTINCT COALESCE(country_name,'') FROM fact_osa_checks "
        "  WHERE osa_type='IR OSA' AND year=:year AND week_number=:wk)"
    ), params)
    db.execute(text(
        "INSERT INTO agg_osa_by_country "
        "  (country_name,channel_name,customer_name,category_name,display_type,total_checks,available_checks) "
        "SELECT COALESCE(country_name,''),COALESCE(channel_name,''),COALESCE(customer_name,''),"
        "       COALESCE(category_name,''),COALESCE(display_type,''),COUNT(*),COALESCE(SUM(osa_flag),0) "
        "FROM fact_osa_checks WHERE osa_type='IR OSA' GROUP BY 1,2,3,4,5"
    ))

    # by_channel
    db.execute(text(
        "DELETE FROM agg_osa_by_channel WHERE channel_name IN ("
        "  SELECT DISTINCT COALESCE(channel_name,'') FROM fact_osa_checks "
        "  WHERE osa_type='IR OSA' AND year=:year AND week_number=:wk)"
    ), params)
    db.execute(text(
        "INSERT INTO agg_osa_by_channel "
        "  (channel_name,country_name,customer_name,category_name,display_type,total_checks,available_checks) "
        "SELECT COALESCE(channel_name,''),COALESCE(country_name,''),COALESCE(customer_name,''),"
        "       COALESCE(category_name,''),COALESCE(display_type,''),COUNT(*),COALESCE(SUM(osa_flag),0) "
        "FROM fact_osa_checks WHERE osa_type='IR OSA' GROUP BY 1,2,3,4,5"
    ))

    # by_display_type
    db.execute(text(
        "DELETE FROM agg_osa_by_display_type WHERE display_type IN ("
        "  SELECT DISTINCT COALESCE(display_type,'') FROM fact_osa_checks "
        "  WHERE osa_type='IR OSA' AND year=:year AND week_number=:wk)"
    ), params)
    db.execute(text(
        "INSERT INTO agg_osa_by_display_type "
        "  (display_type,country_name,channel_name,customer_name,category_name,total_checks,available_checks) "
        "SELECT COALESCE(display_type,''),COALESCE(country_name,''),COALESCE(channel_name,''),"
        "       COALESCE(customer_name,''),COALESCE(category_name,''),COUNT(*),COALESCE(SUM(osa_flag),0) "
        "FROM fact_osa_checks WHERE osa_type='IR OSA' GROUP BY 1,2,3,4,5"
    ))

    # by_category
    db.execute(text(
        "DELETE FROM agg_osa_by_category WHERE category_name IN ("
        "  SELECT DISTINCT COALESCE(category_name,'') FROM fact_osa_checks "
        "  WHERE osa_type='IR OSA' AND year=:year AND week_number=:wk)"
    ), params)
    db.execute(text(
        "INSERT INTO agg_osa_by_category "
        "  (category_name,country_name,channel_name,customer_name,display_type,total_checks,available_checks) "
        "SELECT COALESCE(category_name,''),COALESCE(country_name,''),COALESCE(channel_name,''),"
        "       COALESCE(customer_name,''),COALESCE(display_type,''),COUNT(*),COALESCE(SUM(osa_flag),0) "
        "FROM fact_osa_checks WHERE osa_type='IR OSA' GROUP BY 1,2,3,4,5"
    ))

    # by_account
    db.execute(text(
        "DELETE FROM agg_osa_by_account WHERE customer_name IN ("
        "  SELECT DISTINCT COALESCE(customer_name,'') FROM fact_osa_checks "
        "  WHERE osa_type='IR OSA' AND year=:year AND week_number=:wk)"
    ), params)
    db.execute(text(
        "INSERT INTO agg_osa_by_account "
        "  (customer_name,country_name,channel_name,category_name,display_type,total_checks,available_checks) "
        "SELECT COALESCE(customer_name,''),COALESCE(country_name,''),COALESCE(channel_name,''),"
        "       COALESCE(category_name,''),COALESCE(display_type,''),COUNT(*),COALESCE(SUM(osa_flag),0) "
        "FROM fact_osa_checks WHERE osa_type='IR OSA' GROUP BY 1,2,3,4,5"
    ))

    # by_sku
    db.execute(text(
        "DELETE FROM agg_osa_by_sku WHERE sap_code IN ("
        "  SELECT DISTINCT COALESCE(sap_code,'') FROM fact_osa_checks "
        "  WHERE osa_type='IR OSA' AND year=:year AND week_number=:wk)"
    ), params)
    db.execute(text(
        "INSERT INTO agg_osa_by_sku "
        "  (sap_code,sku_name,country_name,channel_name,customer_name,category_name,display_type,total_checks,available_checks) "
        "SELECT COALESCE(sap_code,''),COALESCE(sku_name,''),COALESCE(country_name,''),COALESCE(channel_name,''),"
        "       COALESCE(customer_name,''),COALESCE(category_name,''),COALESCE(display_type,''),"
        "       COUNT(*),COALESCE(SUM(osa_flag),0) "
        "FROM fact_osa_checks WHERE osa_type='IR OSA' GROUP BY 1,2,3,4,5,6,7"
    ))

    # sku_zero_stores
    db.execute(text(
        "DELETE FROM agg_osa_sku_zero_stores WHERE sap_code IN ("
        "  SELECT DISTINCT COALESCE(sap_code,'') FROM fact_osa_checks "
        "  WHERE osa_type='IR OSA' AND year=:year AND week_number=:wk)"
    ), params)
    db.execute(text(
        "INSERT INTO agg_osa_sku_zero_stores "
        "  (sap_code,store_name,country_name,channel_name,customer_name,category_name,display_type) "
        "SELECT DISTINCT COALESCE(sap_code,''),COALESCE(store_name,''),COALESCE(country_name,''),"
        "       COALESCE(channel_name,''),COALESCE(customer_name,''),COALESCE(category_name,''),"
        "       COALESCE(display_type,'') "
        "FROM fact_osa_checks "
        "WHERE osa_type='IR OSA' AND osa_flag=0 AND store_name IS NOT NULL AND sap_code IS NOT NULL"
    ))


def _refresh_sos(db: Session) -> None:
    """Rebuild all SOS aggregate tables (full rebuild — no week column in fact_share_of_shelf)."""
    db.execute(text("TRUNCATE agg_sos_filter_options"))
    db.execute(text(
        "INSERT INTO agg_sos_filter_options (country_name,channel_name,account_name,display_type) "
        "SELECT DISTINCT COALESCE(country_name,''),COALESCE(channel_name,''),"
        "       COALESCE(account_name,''),COALESCE(display_type,'') "
        "FROM fact_share_of_shelf"
    ))
    db.execute(text("TRUNCATE agg_sos_by_store"))
    db.execute(text(
        "INSERT INTO agg_sos_by_store "
        "  (store_name,country_name,channel_name,account_name,category_name,display_type,row_count,sos_sum) "
        "SELECT COALESCE(store_name,''),COALESCE(country_name,''),COALESCE(channel_name,''),"
        "       COALESCE(account_name,''),COALESCE(category_name,''),COALESCE(display_type,''),"
        "       COUNT(*),COALESCE(SUM(sos_pct),0) "
        "FROM fact_share_of_shelf GROUP BY 1,2,3,4,5,6"
    ))


def _refresh_pog(db: Session) -> None:
    """Rebuild all POG Compliance aggregate tables (full rebuild).

    Country is derived by joining store_name → dim_store.store_name → store_code,
    then looking up country_name from fact_osa_checks (the authoritative
    store→country mapping in this schema).

    fact_pog_compliance_sku is NOT inserted into agg_pog_by_store — it only
    has sku_name, no store/category/country context. The low-compliant-skus
    endpoint queries it directly.
    """
    db.execute(text("TRUNCATE agg_pog_by_store"))

    # ------------------------------------------------------------------
    # Source 1: fact_pog_compliance_category
    #   has: channel_name, customer_name, store_name, category_name
    #   country: store_name → dim_store → fact_osa_checks
    # ------------------------------------------------------------------
    db.execute(text(
        "INSERT INTO agg_pog_by_store "
        "  (store_name, country_name, channel_name, customer_name, category_name, brand_name, row_count, "
        "   pog_compliance_sum, osa_sum, facings_sum, product_placement_sum, assortment_sum) "
        "SELECT "
        "  COALESCE(p.store_name,''), "
        "  COALESCE(("
        "    SELECT DISTINCT o.country_name FROM fact_osa_checks o "
        "    JOIN dim_store ds ON ds.store_code = o.store_code "
        "    WHERE ds.store_name = p.store_name LIMIT 1"
        "  ), ''), "
        "  COALESCE(p.channel_name,''), COALESCE(p.customer_name,''), "
        "  COALESCE(p.category_name,''), '', "
        "  COUNT(*), "
        "  COALESCE(SUM(p.pog_compliance_pct),0), COALESCE(SUM(p.osa_pct),0), "
        "  COALESCE(SUM(p.facings_pct),0), COALESCE(SUM(p.product_placement_pct),0), COALESCE(SUM(p.assortment_pct),0) "
        "FROM fact_pog_compliance_category p "
        "GROUP BY p.store_name, p.channel_name, p.customer_name, p.category_name"
    ))

    # ------------------------------------------------------------------
    # Source 2: fact_pog_compliance_weekly
    #   has: category_name, brand_name, store_name
    #   country: same join path
    # ------------------------------------------------------------------
    db.execute(text(
        "INSERT INTO agg_pog_by_store "
        "  (store_name, country_name, channel_name, customer_name, category_name, brand_name, row_count, "
        "   pog_compliance_sum, osa_sum, facings_sum, product_placement_sum, assortment_sum) "
        "SELECT "
        "  COALESCE(p.store_name,''), "
        "  COALESCE(("
        "    SELECT DISTINCT o.country_name FROM fact_osa_checks o "
        "    JOIN dim_store ds ON ds.store_code = o.store_code "
        "    WHERE ds.store_name = p.store_name LIMIT 1"
        "  ), ''), "
        "  '', '', "
        "  COALESCE(p.category_name,''), COALESCE(p.brand_name,''), "
        "  COUNT(*), "
        "  COALESCE(SUM(p.pog_compliance_pct),0), COALESCE(SUM(p.osa_pct),0), "
        "  COALESCE(SUM(p.facings_pct),0), COALESCE(SUM(p.product_placement_pct),0), COALESCE(SUM(p.assortment_pct),0) "
        "FROM fact_pog_compliance_weekly p "
        "GROUP BY p.store_name, p.category_name, p.brand_name"
    ))

    # ------------------------------------------------------------------
    # Source 3: fact_pog_compliance_store (store rollup — no category/brand)
    #   country: same join path
    # ------------------------------------------------------------------
    db.execute(text(
        "INSERT INTO agg_pog_by_store "
        "  (store_name, country_name, channel_name, customer_name, category_name, brand_name, row_count, "
        "   pog_compliance_sum, osa_sum, facings_sum, product_placement_sum, assortment_sum) "
        "SELECT "
        "  COALESCE(p.store_name,''), "
        "  COALESCE(("
        "    SELECT DISTINCT o.country_name FROM fact_osa_checks o "
        "    JOIN dim_store ds ON ds.store_code = o.store_code "
        "    WHERE ds.store_name = p.store_name LIMIT 1"
        "  ), ''), "
        "  '', '', '', '', "
        "  1, "
        "  COALESCE(p.pog_compliance_pct,0), COALESCE(p.osa_pct,0), "
        "  COALESCE(p.facings_pct,0), COALESCE(p.product_placement_pct,0), COALESCE(p.assortment_pct,0) "
        "FROM fact_pog_compliance_store p"
    ))

    # ------------------------------------------------------------------
    # Rebuild filter options from the populated agg table
    # ------------------------------------------------------------------
    db.execute(text("TRUNCATE agg_pog_filter_options"))
    db.execute(text(
        "INSERT INTO agg_pog_filter_options (country_name, channel_name, customer_name, category_name) "
        "SELECT DISTINCT "
        "  COALESCE(country_name,''), COALESCE(channel_name,''), "
        "  COALESCE(customer_name,''), COALESCE(category_name,'') "
        "FROM agg_pog_by_store "
        "WHERE country_name <> '' OR channel_name <> '' OR customer_name <> '' OR category_name <> ''"
    ))


def _refresh_sod(db: Session) -> None:
    """Rebuild all SOD aggregate tables (full rebuild)."""
    db.execute(text("TRUNCATE agg_sod_filter_options"))
    db.execute(text(
        "INSERT INTO agg_sod_filter_options (country_name,channel_name,account_name,display_type) "
        "SELECT DISTINCT COALESCE(country_name,''),COALESCE(channel_name,''),"
        "       COALESCE(account_name,''),COALESCE(display_type,'') "
        "FROM fact_share_of_display"
    ))
    db.execute(text("TRUNCATE agg_sod_by_store"))
    db.execute(text(
        "INSERT INTO agg_sod_by_store "
        "  (store_name,country_name,channel_name,account_name,category_name,display_type,row_count,sod_sum) "
        "SELECT COALESCE(store_name,''),COALESCE(country_name,''),COALESCE(channel_name,''),"
        "       COALESCE(account_name,''),COALESCE(category_name,''),COALESCE(display_type,''),"
        "       COUNT(*),COALESCE(SUM(sod_pct),0) "
        "FROM fact_share_of_display GROUP BY 1,2,3,4,5,6"
    ))


# ── Available weeks ───────────────────────────────────────────────────────────

@router.get("/available-weeks")
def get_available_weeks(
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(1)),
):
    """
    Merged distinct weeks from all three fact tables, newest first.
    Uses fact_osa_checks as the primary source (week-granular data).
    SOS and SOD also carry year/week_number so we include those too.
    """
    rows = db.execute(
        text(
            "SELECT DISTINCT year, week_number, week_label FROM fact_osa_checks "
            "WHERE osa_type='IR OSA' AND year IS NOT NULL AND week_number IS NOT NULL "
            "UNION "
            "SELECT DISTINCT year, week_number, week_label FROM fact_share_of_shelf "
            "WHERE year IS NOT NULL AND week_number IS NOT NULL "
            "UNION "
            "SELECT DISTINCT year, week_number, week_label FROM fact_share_of_display "
            "WHERE year IS NOT NULL AND week_number IS NOT NULL "
            "ORDER BY 1 DESC, 2 DESC"
        )
    ).fetchall()

    seen: set = set()
    result = []
    for r in rows:
        key = (r[0], r[1])
        if key not in seen:
            seen.add(key)
            result.append({
                "year":        r[0],
                "week_number": r[1],
                "week_label":  r[2] or f"W{r[1]} {r[0]}",
            })
    return result


# ── Unified refresh (all sections) ────────────────────────────────────────────

def _do_refresh(body: RefreshRequest, db: Session) -> dict:
    year, week_number = body.year, body.week_number

    # Validate week exists in at least one fact table
    osa_exists = db.execute(
        text("SELECT 1 FROM fact_osa_checks WHERE osa_type='IR OSA' "
             "AND year=:year AND week_number=:wk LIMIT 1"),
        {"year": year, "wk": week_number},
    ).fetchone()
    sos_exists = db.execute(
        text("SELECT 1 FROM fact_share_of_shelf WHERE year=:year AND week_number=:wk LIMIT 1"),
        {"year": year, "wk": week_number},
    ).fetchone()
    sod_exists = db.execute(
        text("SELECT 1 FROM fact_share_of_display WHERE year=:year AND week_number=:wk LIMIT 1"),
        {"year": year, "wk": week_number},
    ).fetchone()

    # POG tables have no week dimension — always rebuild if any fact data exists
    pog_exists = db.execute(
        text("SELECT 1 FROM fact_pog_compliance_category LIMIT 1")
    ).fetchone()
    if not pog_exists:
        pog_exists = db.execute(
            text("SELECT 1 FROM fact_pog_compliance_weekly LIMIT 1")
        ).fetchone()
    if not pog_exists:
        pog_exists = db.execute(
            text("SELECT 1 FROM fact_pog_compliance_store LIMIT 1")
        ).fetchone()
    if not pog_exists:
        pog_exists = db.execute(
            text("SELECT 1 FROM fact_pog_compliance_sku LIMIT 1")
        ).fetchone()

    if not any([osa_exists, sos_exists, sod_exists, pog_exists]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No data found in any fact table for Year {year}, Week {week_number}.",
        )

    sections_refreshed = []
    try:
        if osa_exists:
            _refresh_osa(db, year, week_number)
            sections_refreshed.append("Availability (OSA)")

        if sos_exists:
            _refresh_sos(db)
            sections_refreshed.append("Share of Shelf (SOS)")

        if sod_exists:
            _refresh_sod(db)
            sections_refreshed.append("Share of Display (SOD)")

        if pog_exists:
            _refresh_pog(db)
            sections_refreshed.append("Planogram Compliance (POG)")

        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Refresh failed: {exc}",
        )

    invalidate_availability()  # flushes all vs:avail:* Redis keys

    return {
        "success":            True,
        "year":               year,
        "week_number":        week_number,
        "sections_refreshed": sections_refreshed,
        "message": (
            f"Refreshed {', '.join(sections_refreshed)} for "
            f"Year {year} / Week {week_number}. Redis cache cleared."
        ),
    }


@router.post("/refresh-all-aggregates")
def refresh_all_aggregates(
    body: RefreshRequest,
    db:   Session     = Depends(get_db),
    ctx:  UserContext = Depends(require_minimum_tier(1)),
):
    return _do_refresh(body, db)


@router.post("/refresh-aggregates")
def refresh_aggregates(
    body: RefreshRequest,
    db:   Session     = Depends(get_db),
    ctx:  UserContext = Depends(require_minimum_tier(1)),
):
    """Backward-compatible alias for refresh-all-aggregates."""
    return _do_refresh(body, db)


@router.post("/refresh-pog")
def refresh_pog_only(
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(1)),
):
    """
    Rebuild only the POG Compliance aggregate tables.
    No week param needed — POG fact tables have no week dimension.
    Flushes Redis cache after rebuild.
    """
    try:
        _refresh_pog(db)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"POG refresh failed: {exc}",
        )

    invalidate_availability()
    return {
        "success": True,
        "message": "Planogram Compliance aggregates rebuilt. Redis cache cleared.",
    }
