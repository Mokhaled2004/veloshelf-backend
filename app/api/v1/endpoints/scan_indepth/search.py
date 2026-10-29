"""
GET /scan/search?mode=sku|category|store&q=<query>
GET /scan/quick-suggestions?mode=sku|category|store

Autocomplete and quick suggestions for the Scan Indepth search panel.
"""

from fastapi import Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.scan_indepth.router import router


def _clean(val) -> str:
    """Return a clean string, stripping trailing .0 from numeric-cast values."""
    s = str(val or "").strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


@router.get("/search")
def search_suggestions(
    mode: str = Query(..., description="sku | category | store"),
    q:    str = Query("", description="search term"),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    q_clean = q.strip()
    cache_key = build_key(f"scan_search_{mode}", q=q_clean, scope_countries=sorted(ctx.countries))
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    results: list[dict] = []
    pattern = f"%{q_clean}%"

    if mode == "sku":
        # Search in dim_sku AND in fact_osa_checks sku_name (they may differ)
        rows = db.execute(
            text(
                "SELECT DISTINCT ON (COALESCE(s.sap_code, f.sap_code)) "
                "  COALESCE(s.sap_code, f.sap_code) AS sap_code, "
                "  COALESCE(s.sku_name, f.sku_name)  AS sku_name, "
                "  s.barcode, "
                "  COALESCE(s.category_name, f.category_name) AS category_name "
                "FROM fact_osa_checks f "
                "LEFT JOIN dim_sku s ON s.sap_code = f.sap_code "
                "WHERE f.osa_type = 'IR OSA' "
                "  AND (COALESCE(s.sku_name, f.sku_name) ILIKE :p "
                "       OR COALESCE(s.sap_code, f.sap_code) ILIKE :p "
                "       OR s.barcode ILIKE :p) "
                "ORDER BY COALESCE(s.sap_code, f.sap_code), COALESCE(s.sku_name, f.sku_name) "
                "LIMIT 8"
            ),
            {"p": pattern},
        ).fetchall()
        results = [
            {
                "id":       _clean(r[0]),
                "label":    _clean(r[1]) or _clean(r[0]),
                "sub":      _clean(r[0]),
                "barcode":  _clean(r[2]),
                "category": _clean(r[3]),
            }
            for r in rows
            if r[0]
        ]

    elif mode == "category":
        rows = db.execute(
            text(
                "SELECT DISTINCT dc.category_name, dc.nestle_category "
                "FROM dim_category dc "
                "JOIN fact_osa_checks f ON f.category_name = dc.category_name "
                "WHERE f.osa_type = 'IR OSA' "
                "  AND (dc.category_name ILIKE :p OR dc.nestle_category ILIKE :p) "
                "ORDER BY dc.category_name "
                "LIMIT 8"
            ),
            {"p": pattern},
        ).fetchall()
        results = [
            {"id": _clean(r[0]), "label": _clean(r[0]), "sub": _clean(r[1])}
            for r in rows if r[0]
        ]

    elif mode == "store":
        scope_clause = ""
        params: dict = {"p": pattern}
        if not ctx.is_unrestricted and ctx.stores:
            scope_clause = "AND ds.store_code = ANY(:scope_stores)"
            params["scope_stores"] = ctx.stores
        rows = db.execute(
            text(
                f"SELECT DISTINCT ds.store_code, ds.store_name "
                f"FROM dim_store ds "
                f"JOIN fact_osa_checks f ON f.store_code = ds.store_code "
                f"WHERE f.osa_type = 'IR OSA' "
                f"  AND (ds.store_name ILIKE :p OR ds.store_code ILIKE :p) "
                f"{scope_clause} "
                f"ORDER BY ds.store_name "
                f"LIMIT 8"
            ),
            params,
        ).fetchall()
        results = [
            {"id": _clean(r[0]), "label": _clean(r[1]) or _clean(r[0]), "sub": _clean(r[0])}
            for r in rows if r[0]
        ]

    set_cached(cache_key, results, ttl=300)
    return results


@router.get("/quick-suggestions")
def quick_suggestions(
    mode: str = Query(..., description="sku | category | store"),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    """Top 5 most-scanned items per mode — sourced from fact_osa_checks directly."""
    cache_key = build_key(f"scan_quick_{mode}", scope_countries=sorted(ctx.countries))
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    results: list[dict] = []

    if mode == "sku":
        # Use fact_osa_checks directly — guaranteed to be real data in the db
        rows = db.execute(
            text(
                "SELECT sap_code, sku_name, COUNT(*) AS tc "
                "FROM fact_osa_checks "
                "WHERE osa_type = 'IR OSA' AND sap_code IS NOT NULL AND sap_code <> '' "
                "  AND sku_name IS NOT NULL AND sku_name <> '' "
                "GROUP BY sap_code, sku_name "
                "ORDER BY tc DESC "
                "LIMIT 5"
            )
        ).fetchall()
        results = [
            {"id": _clean(r[0]), "label": _clean(r[1]), "sub": _clean(r[0])}
            for r in rows
        ]

    elif mode == "category":
        rows = db.execute(
            text(
                "SELECT f.category_name, dc.nestle_category, COUNT(*) AS tc "
                "FROM fact_osa_checks f "
                "LEFT JOIN dim_category dc ON dc.category_name = f.category_name "
                "WHERE f.osa_type = 'IR OSA' AND f.category_name IS NOT NULL AND f.category_name <> '' "
                "GROUP BY f.category_name, dc.nestle_category "
                "ORDER BY tc DESC "
                "LIMIT 5"
            )
        ).fetchall()
        results = [
            {"id": _clean(r[0]), "label": _clean(r[0]), "sub": _clean(r[1])}
            for r in rows
        ]

    elif mode == "store":
        rows = db.execute(
            text(
                "SELECT f.store_code, f.store_name, COUNT(*) AS tc "
                "FROM fact_osa_checks f "
                "WHERE f.osa_type = 'IR OSA' "
                "  AND f.store_code IS NOT NULL AND f.store_code <> '' "
                "  AND f.store_name IS NOT NULL AND f.store_name <> '' "
                "GROUP BY f.store_code, f.store_name "
                "ORDER BY tc DESC "
                "LIMIT 5"
            )
        ).fetchall()
        results = [
            {"id": _clean(r[0]), "label": _clean(r[1]), "sub": _clean(r[0])}
            for r in rows
        ]

    set_cached(cache_key, results, ttl=600)
    return results
