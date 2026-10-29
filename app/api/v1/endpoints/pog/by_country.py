"""GET /pog/by-country — POG compliance grouped by country."""

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

_METRICS = (
    "pog_compliance_sum", "osa_sum", "facings_sum",
    "product_placement_sum", "assortment_sum",
)


def _row_to_dict(country: str, row_count: int, sums: tuple) -> dict:
    def pct(s): return round(float(s or 0) / row_count, 2) if row_count else 0.0
    return {
        "country":               country or "Unknown",
        "pog_compliance_pct":    pct(sums[0]),
        "osa_pct":               pct(sums[1]),
        "facings_pct":           pct(sums[2]),
        "product_placement_pct": pct(sums[3]),
        "assortment_pct":        pct(sums[4]),
        "total_records":         row_count,
    }


@router.get("/by-country")
def get_pog_by_country(
    channel:  Optional[Union[str, list[str]]] = Query(None),
    category: Optional[Union[str, list[str]]] = Query(None),
    customer: Optional[Union[str, list[str]]] = Query(None),
    brand:    Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    channel_list  = normalise_list(channel)
    category_list = normalise_list(category)
    customer_list = normalise_list(customer)
    brand_list    = normalise_list(brand)
    cat_names     = resolve_category_names(db, category_list)

    cache_key = build_key(
        "pog_by_country",
        channel=channel_list, category=cat_names,
        customer=customer_list, brand=brand_list,
        scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    where, params = build_where(
        country=[], channel=channel_list,
        customer=customer_list, category_names=cat_names,
        brand=brand_list,
        scope_countries=ctx.countries,
        is_unrestricted=ctx.is_unrestricted,
    )

    rows = db.execute(
        text(
            f"SELECT country_name, "
            f"       SUM(row_count), "
            f"       SUM(pog_compliance_sum), SUM(osa_sum), "
            f"       SUM(facings_sum), SUM(product_placement_sum), SUM(assortment_sum) "
            f"FROM agg_pog_by_store {where} "
            f"{'AND' if where else 'WHERE'} country_name <> '' "
            f"GROUP BY country_name ORDER BY country_name"
        ),
        params,
    ).fetchall()

    result = [_row_to_dict(r[0], int(r[1] or 0), r[2:7]) for r in rows]
    set_cached(cache_key, result)
    return result
