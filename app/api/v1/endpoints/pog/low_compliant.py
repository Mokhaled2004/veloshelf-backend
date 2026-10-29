"""
GET /pog/low-compliant-skus    — bottom 15 SKUs by POG compliance %
GET /pog/low-compliant-stores  — bottom 15 stores by POG compliance %

Both endpoints read directly from fact_pog_compliance_sku and
fact_pog_compliance_store respectively (rollup tables with no filter dims),
falling back to agg_pog_by_store for filter-aware queries.
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

_LIMIT = 15


@router.get("/low-compliant-skus")
def get_pog_low_compliant_skus(
    country:  Optional[Union[str, list[str]]] = Query(None),
    channel:  Optional[Union[str, list[str]]] = Query(None),
    category: Optional[Union[str, list[str]]] = Query(None),
    customer: Optional[Union[str, list[str]]] = Query(None),
    brand:    Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    country_list  = normalise_list(country)
    channel_list  = normalise_list(channel)
    category_list = normalise_list(category)
    customer_list = normalise_list(customer)
    brand_list    = normalise_list(brand)
    cat_names     = resolve_category_names(db, category_list)

    cache_key = build_key(
        "pog_low_skus",
        country=country_list, channel=channel_list,
        category=cat_names, customer=customer_list, brand=brand_list,
        scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    # Query fact_pog_compliance_sku directly — this table has sku_name + all 5 metrics
    # No filter dims available on this table, so filters are ignored for SKU ranking
    rows = db.execute(
        text(
            f"SELECT sku_name, "
            f"       pog_compliance_pct "
            f"FROM fact_pog_compliance_sku "
            f"WHERE pog_compliance_pct IS NOT NULL "
            f"ORDER BY pog_compliance_pct ASC "
            f"LIMIT {_LIMIT}"
        ),
        {},
    ).fetchall()

    result = [
        {
            "name":               r[0] or "Unknown",
            "pog_compliance_pct": round(float(r[1] or 0), 2),
            "total_records":      1,
        }
        for r in rows
    ]
    set_cached(cache_key, result)
    return result


@router.get("/low-compliant-stores")
def get_pog_low_compliant_stores(
    country:  Optional[Union[str, list[str]]] = Query(None),
    channel:  Optional[Union[str, list[str]]] = Query(None),
    category: Optional[Union[str, list[str]]] = Query(None),
    customer: Optional[Union[str, list[str]]] = Query(None),
    brand:    Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    country_list  = normalise_list(country)
    channel_list  = normalise_list(channel)
    category_list = normalise_list(category)
    customer_list = normalise_list(customer)
    brand_list    = normalise_list(brand)
    cat_names     = resolve_category_names(db, category_list)

    cache_key = build_key(
        "pog_low_stores",
        country=country_list, channel=channel_list,
        category=cat_names, customer=customer_list, brand=brand_list,
        scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    where, params = build_where(
        country=country_list, channel=channel_list,
        customer=customer_list, category_names=cat_names,
        brand=brand_list,
        scope_countries=ctx.countries,
        is_unrestricted=ctx.is_unrestricted,
    )

    rows = db.execute(
        text(
            f"SELECT store_name, country_name, "
            f"       SUM(row_count) AS rc, "
            f"       SUM(pog_compliance_sum) "
            f"FROM agg_pog_by_store {where} "
            f"GROUP BY store_name, country_name "
            f"HAVING SUM(row_count) > 0 "
            f"ORDER BY (SUM(pog_compliance_sum) / NULLIF(SUM(row_count),0)) ASC "
            f"LIMIT {_LIMIT}"
        ),
        params,
    ).fetchall()

    result = [
        {
            "name":               r[0] or "Unknown",
            "country":            r[1] or "",
            "pog_compliance_pct": round(float(r[3] or 0) / int(r[2]), 2) if int(r[2] or 0) else 0.0,
            "total_records":      int(r[2] or 0),
        }
        for r in rows
    ]
    set_cached(cache_key, result)
    return result
