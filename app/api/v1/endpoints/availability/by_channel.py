"""
GET /availability/osa-by-channel
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


@router.get("/osa-by-channel")
def get_osa_by_channel(
    country:      Optional[Union[str, list[str]]] = Query(None),
    category:     Optional[Union[str, list[str]]] = Query(None),
    account:      Optional[Union[str, list[str]]] = Query(None),
    display_type: Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    country_list  = normalise_list(country)
    category_list = normalise_list(category)
    account_list  = normalise_list(account)
    display_list  = normalise_list(display_type)
    cat_names     = resolve_category_names(db, category_list)

    cache_key = build_key(
        "osa_by_channel",
        country=country_list, category=cat_names,
        account=account_list, display_type=display_list,
        scope_countries=sorted(ctx.countries),
        scope_stores=sorted(ctx.stores),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    where, params = build_where(
        country=country_list, channel=[],
        customer=account_list, category_names=cat_names,
        display_type=display_list,
        scope_countries=ctx.countries,
        scope_stores=ctx.stores,
        is_unrestricted=ctx.is_unrestricted,
    )

    if not ctx.is_unrestricted and ctx.stores:
        store_clause = "store_code = ANY(:_scope_stores)"
        params["_scope_stores"] = ctx.stores
        where = f"{where} AND {store_clause}" if where else f"WHERE {store_clause}"

    rows = db.execute(
        text(
            f"SELECT channel_name, "
            f"       SUM(total_checks) AS total, "
            f"       SUM(available_checks) AS avail "
            f"FROM agg_osa_by_store "
            f"{where} "
            f"GROUP BY channel_name "
            f"ORDER BY channel_name"
        ),
        params,
    ).fetchall()

    result = [
        {
            "channel":         r[0] or "Unknown",
            "osa_percentage":  round(r[2] / r[1] * 100, 2) if r[1] else 0.0,
            "total_checks":    int(r[1] or 0),
            "available_checks": int(r[2] or 0),
        }
        for r in rows
    ]
    set_cached(cache_key, result)
    return result
