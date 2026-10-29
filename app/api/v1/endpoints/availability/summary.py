"""
GET /availability/osa-summary

Returns overall OSA % + total / available checks for the current filter set.
Reads from agg_osa_by_store (finest grain available in agg tables so every
combination of filters can be answered without hitting the fact table).
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


@router.get("/osa-summary")
def get_osa_summary(
    country:      Optional[Union[str, list[str]]] = Query(None),
    channel:      Optional[Union[str, list[str]]] = Query(None),
    category:     Optional[Union[str, list[str]]] = Query(None),
    account:      Optional[Union[str, list[str]]] = Query(None),
    display_type: Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    country_list   = normalise_list(country)
    channel_list   = normalise_list(channel)
    category_list  = normalise_list(category)
    account_list   = normalise_list(account)
    display_list   = normalise_list(display_type)
    cat_names      = resolve_category_names(db, category_list)

    cache_key = build_key(
        "osa_summary",
        country=country_list, channel=channel_list,
        category=cat_names, account=account_list,
        display_type=display_list,
        scope_countries=sorted(ctx.countries),
        scope_stores=sorted(ctx.stores),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    where, params = build_where(
        country=country_list, channel=channel_list,
        customer=account_list, category_names=cat_names,
        display_type=display_list,
        scope_countries=ctx.countries,
        scope_stores=ctx.stores,
        is_unrestricted=ctx.is_unrestricted,
    )

    # agg_osa_by_store is the finest-grain table → can answer any filter set
    base_table = "agg_osa_by_store"

    # Store-scoped users need an extra restriction on store_code
    if not ctx.is_unrestricted and ctx.stores:
        store_clause = "store_code = ANY(:_scope_stores)"
        params["_scope_stores"] = ctx.stores
        where = f"{where} AND {store_clause}" if where else f"WHERE {store_clause}"

    row = db.execute(
        text(f"SELECT SUM(total_checks), SUM(available_checks) FROM {base_table} {where}"),
        params,
    ).fetchone()

    total     = int(row[0] or 0)
    available = int(row[1] or 0)

    if total == 0:
        result = {
            "osa_percentage":  0.0,
            "total_checks":    0,
            "available_checks": 0,
            "message": "No data found within your assigned scope.",
        }
    else:
        result = {
            "osa_percentage":   round(available / total * 100, 2),
            "total_checks":     total,
            "available_checks": available,
            "user_tier":        ctx.tier,
            "is_unrestricted":  ctx.is_unrestricted,
        }

    set_cached(cache_key, result)
    return result
