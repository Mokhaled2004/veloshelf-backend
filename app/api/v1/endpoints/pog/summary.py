"""
GET /pog/summary

Returns the 5 KPI averages shown in the top number cards:
  - pog_compliance_pct  (POG Compliance)
  - assortment_pct      (Assortment)
  - product_placement_pct (Product Placement)
  - osa_pct             (OSA)
  - facings_pct         (Facings Score)

Each metric is a weighted average across agg_pog_by_store
(SUM of _sum / SUM of row_count) so every store row contributes equally
regardless of which table it was sourced from.
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


@router.get("/summary")
def get_pog_summary(
    country:  Optional[Union[str, list[str]]] = Query(None),
    channel:  Optional[Union[str, list[str]]] = Query(None),
    category: Optional[Union[str, list[str]]] = Query(None),
    customer: Optional[Union[str, list[str]]] = Query(None),
    brand:    Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    country_list   = normalise_list(country)
    channel_list   = normalise_list(channel)
    category_list  = normalise_list(category)
    customer_list  = normalise_list(customer)
    brand_list     = normalise_list(brand)
    cat_names      = resolve_category_names(db, category_list)

    cache_key = build_key(
        "pog_summary",
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

    row = db.execute(
        text(
            f"SELECT "
            f"  SUM(row_count)               AS total_rows, "
            f"  SUM(pog_compliance_sum)       AS pog_sum, "
            f"  SUM(osa_sum)                  AS osa_s, "
            f"  SUM(facings_sum)              AS fac_s, "
            f"  SUM(product_placement_sum)    AS pp_s, "
            f"  SUM(assortment_sum)           AS ass_s "
            f"FROM agg_pog_by_store {where}"
        ),
        params,
    ).fetchone()

    total = int(row[0] or 0)

    def pct(s) -> float:
        return round(float(s or 0) / total, 2) if total else 0.0

    if total == 0:
        result = {
            "pog_compliance_pct":     0.0,
            "osa_pct":                0.0,
            "facings_pct":            0.0,
            "product_placement_pct":  0.0,
            "assortment_pct":         0.0,
            "total_records":          0,
            "message": "No data found within your assigned scope.",
        }
    else:
        result = {
            "pog_compliance_pct":    pct(row[1]),
            "osa_pct":               pct(row[2]),
            "facings_pct":           pct(row[3]),
            "product_placement_pct": pct(row[4]),
            "assortment_pct":        pct(row[5]),
            "total_records":         total,
        }

    set_cached(cache_key, result)
    return result
