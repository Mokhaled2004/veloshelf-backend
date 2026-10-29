"""GET /pog/by-brand — POG compliance grouped by brand."""

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


@router.get("/by-brand")
def get_pog_by_brand(
    country:  Optional[Union[str, list[str]]] = Query(None),
    channel:  Optional[Union[str, list[str]]] = Query(None),
    category: Optional[Union[str, list[str]]] = Query(None),
    customer: Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    country_list  = normalise_list(country)
    channel_list  = normalise_list(channel)
    category_list = normalise_list(category)
    customer_list = normalise_list(customer)
    cat_names     = resolve_category_names(db, category_list)

    cache_key = build_key(
        "pog_by_brand",
        country=country_list, channel=channel_list,
        category=cat_names, customer=customer_list,
        scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    where, params = build_where(
        country=country_list, channel=channel_list,
        customer=customer_list, category_names=cat_names,
        brand=[],
        scope_countries=ctx.countries,
        is_unrestricted=ctx.is_unrestricted,
    )

    rows = db.execute(
        text(
            f"SELECT brand_name, "
            f"       SUM(row_count), "
            f"       SUM(pog_compliance_sum), SUM(osa_sum), "
            f"       SUM(facings_sum), SUM(product_placement_sum), SUM(assortment_sum) "
            f"FROM agg_pog_by_store {where} "
            f"GROUP BY brand_name ORDER BY brand_name"
        ),
        params,
    ).fetchall()

    result = []
    for r in rows:
        total = int(r[1] or 0)
        def pct(s): return round(float(s or 0) / total, 2) if total else 0.0
        result.append({
            "brand":                 r[0] or "Unknown",
            "pog_compliance_pct":    pct(r[2]),
            "osa_pct":               pct(r[3]),
            "facings_pct":           pct(r[4]),
            "product_placement_pct": pct(r[5]),
            "assortment_pct":        pct(r[6]),
            "total_records":         total,
        })

    set_cached(cache_key, result)
    return result
