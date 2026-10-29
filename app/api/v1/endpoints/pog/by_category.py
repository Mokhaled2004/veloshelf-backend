"""
GET /pog/by-category      — grouped by raw category_name
GET /pog/by-nestle-category — grouped by nestle_category (UI label)
"""

from typing import Optional, Union

from fastapi import Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.pog.filters import (
    normalise_list, resolve_category_names, build_where,
)
from app.api.v1.endpoints.pog.router import router


def _to_pct(val, total: int) -> float:
    return round(float(val or 0) / total, 2) if total else 0.0


def _build_result(label_col: str, rows) -> list[dict]:
    result = []
    for r in rows:
        total = int(r[1] or 0)
        result.append({
            "category":              r[0] or "Unknown",
            "pog_compliance_pct":    _to_pct(r[2], total),
            "osa_pct":               _to_pct(r[3], total),
            "facings_pct":           _to_pct(r[4], total),
            "product_placement_pct": _to_pct(r[5], total),
            "assortment_pct":        _to_pct(r[6], total),
            "total_records":         total,
        })
    return result


@router.get("/by-category")
def get_pog_by_category(
    country:  Optional[Union[str, list[str]]] = Query(None),
    channel:  Optional[Union[str, list[str]]] = Query(None),
    customer: Optional[Union[str, list[str]]] = Query(None),
    brand:    Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    country_list  = normalise_list(country)
    channel_list  = normalise_list(channel)
    customer_list = normalise_list(customer)
    brand_list    = normalise_list(brand)

    cache_key = build_key(
        "pog_by_category",
        country=country_list, channel=channel_list,
        customer=customer_list, brand=brand_list,
        scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    where, params = build_where(
        country=country_list, channel=channel_list,
        customer=customer_list, category_names=[],
        brand=brand_list,
        scope_countries=ctx.countries,
        is_unrestricted=ctx.is_unrestricted,
    )

    rows = db.execute(
        text(
            f"SELECT category_name, "
            f"       SUM(row_count), "
            f"       SUM(pog_compliance_sum), SUM(osa_sum), "
            f"       SUM(facings_sum), SUM(product_placement_sum), SUM(assortment_sum) "
            f"FROM agg_pog_by_store {where} "
            f"{'AND' if where else 'WHERE'} category_name <> '' "
            f"GROUP BY category_name ORDER BY category_name"
        ),
        params,
    ).fetchall()

    result = _build_result("category_name", rows)
    set_cached(cache_key, result)
    return result


@router.get("/by-nestle-category")
def get_pog_by_nestle_category(
    country:  Optional[Union[str, list[str]]] = Query(None),
    channel:  Optional[Union[str, list[str]]] = Query(None),
    customer: Optional[Union[str, list[str]]] = Query(None),
    brand:    Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    country_list  = normalise_list(country)
    channel_list  = normalise_list(channel)
    customer_list = normalise_list(customer)
    brand_list    = normalise_list(brand)

    cache_key = build_key(
        "pog_by_nestle_cat",
        country=country_list, channel=channel_list,
        customer=customer_list, brand=brand_list,
        scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    # Build clauses manually with aliased table prefix
    clauses: list[str] = []
    params: dict = {}

    if not ctx.is_unrestricted and ctx.countries:
        clauses.append("a.country_name = ANY(:scope_countries)")
        params["scope_countries"] = ctx.countries

    if country_list:
        clauses.append("a.country_name = ANY(:country)")
        params["country"] = country_list

    if channel_list:
        clauses.append("a.channel_name = ANY(:channel)")
        params["channel"] = channel_list

    if customer_list:
        clauses.append("a.customer_name = ANY(:customer)")
        params["customer"] = customer_list

    if brand_list:
        clauses.append("a.brand_name = ANY(:brand)")
        params["brand"] = brand_list

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    rows = db.execute(
        text(
            f"SELECT COALESCE(dc.nestle_category, a.category_name) AS nestle_cat, "
            f"       SUM(a.row_count), "
            f"       SUM(a.pog_compliance_sum), SUM(a.osa_sum), "
            f"       SUM(a.facings_sum), SUM(a.product_placement_sum), SUM(a.assortment_sum) "
            f"FROM agg_pog_by_store a "
            f"LEFT JOIN dim_category dc ON dc.category_name = a.category_name "
            f"{where} "
            f"AND a.category_name <> '' "
            f"GROUP BY 1 ORDER BY 1"
        ),
        params,
    ).fetchall()

    result = _build_result("nestle_cat", rows)
    set_cached(cache_key, result)
    return result
