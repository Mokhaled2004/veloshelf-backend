"""
GET /pog/top-stores    — top 10 stores by POG compliance %
GET /pog/bottom-stores — bottom 10 stores by POG compliance %
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

_LIMIT = 10
_MIN_ROWS = 3  # ignore stores with almost no data


def _fetch_stores(db, where, params, order: str) -> list[dict]:
    rows = db.execute(
        text(
            f"SELECT store_name, country_name, "
            f"       SUM(row_count) AS rc, "
            f"       SUM(pog_compliance_sum), SUM(osa_sum), "
            f"       SUM(facings_sum), SUM(product_placement_sum), SUM(assortment_sum) "
            f"FROM agg_pog_by_store {where} "
            f"GROUP BY store_name, country_name "
            f"HAVING SUM(row_count) >= {_MIN_ROWS} "
            f"ORDER BY (SUM(pog_compliance_sum) / NULLIF(SUM(row_count),0)) {order} "
            f"LIMIT {_LIMIT}"
        ),
        params,
    ).fetchall()

    result = []
    for r in rows:
        rc = int(r[2] or 0)
        def pct(s): return round(float(s or 0) / rc, 2) if rc else 0.0
        result.append({
            "store_name":            r[0] or "Unknown",
            "country":               r[1] or "",
            "pog_compliance_pct":    pct(r[3]),
            "osa_pct":               pct(r[4]),
            "facings_pct":           pct(r[5]),
            "product_placement_pct": pct(r[6]),
            "assortment_pct":        pct(r[7]),
            "total_records":         rc,
        })
    return result


def _common_params(
    country, channel, category, customer, brand, db, ctx
):
    country_list  = normalise_list(country)
    channel_list  = normalise_list(channel)
    category_list = normalise_list(category)
    customer_list = normalise_list(customer)
    brand_list    = normalise_list(brand)
    cat_names     = resolve_category_names(db, category_list)
    where, params = build_where(
        country=country_list, channel=channel_list,
        customer=customer_list, category_names=cat_names,
        brand=brand_list,
        scope_countries=ctx.countries,
        is_unrestricted=ctx.is_unrestricted,
    )
    return where, params, country_list, channel_list, cat_names, customer_list, brand_list


@router.get("/top-stores")
def get_pog_top_stores(
    country:  Optional[Union[str, list[str]]] = Query(None),
    channel:  Optional[Union[str, list[str]]] = Query(None),
    category: Optional[Union[str, list[str]]] = Query(None),
    customer: Optional[Union[str, list[str]]] = Query(None),
    brand:    Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    where, params, c, ch, cn, cu, b = _common_params(
        country, channel, category, customer, brand, db, ctx
    )
    cache_key = build_key(
        "pog_top_stores",
        country=c, channel=ch, category=cn, customer=cu, brand=b,
        scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    result = _fetch_stores(db, where, params, "DESC")
    set_cached(cache_key, result)
    return result


@router.get("/bottom-stores")
def get_pog_bottom_stores(
    country:  Optional[Union[str, list[str]]] = Query(None),
    channel:  Optional[Union[str, list[str]]] = Query(None),
    category: Optional[Union[str, list[str]]] = Query(None),
    customer: Optional[Union[str, list[str]]] = Query(None),
    brand:    Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    where, params, c, ch, cn, cu, b = _common_params(
        country, channel, category, customer, brand, db, ctx
    )
    cache_key = build_key(
        "pog_bottom_stores",
        country=c, channel=ch, category=cn, customer=cu, brand=b,
        scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    result = _fetch_stores(db, where, params, "ASC")
    set_cached(cache_key, result)
    return result
