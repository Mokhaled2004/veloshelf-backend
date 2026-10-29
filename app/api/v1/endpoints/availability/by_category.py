"""
GET /availability/osa-by-category

Groups by nestle_category (the UI-facing label) by joining agg_osa_by_category
with dim_category at query time.  dim_category is tiny so the join is free.
"""

from typing import Optional, Union

from fastapi import Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.availability.filters import (
    normalise_list, resolve_category_names, build_where,
)
from app.api.v1.endpoints.availability.router import router


@router.get("/osa-by-category")
def get_osa_by_category(
    country:      Optional[Union[str, list[str]]] = Query(None),
    channel:      Optional[Union[str, list[str]]] = Query(None),
    account:      Optional[Union[str, list[str]]] = Query(None),
    display_type: Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    country_list = normalise_list(country)
    channel_list = normalise_list(channel)
    account_list = normalise_list(account)
    display_list = normalise_list(display_type)

    cache_key = build_key(
        "osa_by_category",
        country=country_list, channel=channel_list,
        account=account_list, display_type=display_list,
        scope_countries=sorted(ctx.countries),
        scope_stores=sorted(ctx.stores),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    where, params = build_where(
        country=country_list, channel=channel_list,
        customer=account_list, category_names=[],   # no category filter here
        display_type=display_list,
        scope_countries=ctx.countries,
        scope_stores=ctx.stores,
        is_unrestricted=ctx.is_unrestricted,
    )

    # Build a scope-aware alias for the table
    store_extra = ""
    if not ctx.is_unrestricted and ctx.stores:
        store_clause = "a.store_code = ANY(:_scope_stores)"
        params["_scope_stores"] = ctx.stores
        store_extra = f" AND {store_clause}"

    # Join with dim_category to group by nestle_category
    # agg_osa_by_store carries category_name so we can join on that
    where_with_alias = where.replace("country_name", "a.country_name") \
                            .replace("channel_name", "a.channel_name") \
                            .replace("customer_name", "a.customer_name") \
                            .replace("display_type",  "a.display_type") \
                            .replace("category_name", "a.category_name")

    rows = db.execute(
        text(
            f"SELECT dc.nestle_category, "
            f"       SUM(a.total_checks) AS total, "
            f"       SUM(a.available_checks) AS avail "
            f"FROM agg_osa_by_store a "
            f"JOIN dim_category dc ON dc.category_name = a.category_name "
            f"{where_with_alias}{store_extra} "
            f"GROUP BY dc.nestle_category "
            f"ORDER BY dc.nestle_category"
        ),
        params,
    ).fetchall()

    result = [
        {
            "category":        r[0] or "Unknown Nestle Category",
            "osa_percentage":  round(r[2] / r[1] * 100, 2) if r[1] else 0.0,
            "total_checks":    int(r[1] or 0),
            "available_checks": int(r[2] or 0),
        }
        for r in rows
    ]
    set_cached(cache_key, result)
    return result
