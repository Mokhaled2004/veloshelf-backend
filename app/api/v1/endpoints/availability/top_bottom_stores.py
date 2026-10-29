"""
GET /availability/osa-top-stores
GET /availability/osa-bottom-stores

Both read from agg_osa_by_store, grouping to store level,
applying a minimum-checks guard, then sorting by OSA %.
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

# Minimum total checks for a store to appear in top/bottom lists
_MIN_CHECKS = 5


def _query_stores(
    db: Session,
    ctx: UserContext,
    country_list: list[str],
    channel_list: list[str],
    cat_names: list[str],
    account_list: list[str],
    display_list: list[str],
    order: str,   # "DESC" or "ASC"
) -> list[dict]:
    where, params = build_where(
        country=country_list, channel=channel_list,
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
            f"SELECT store_code, store_name, "
            f"       SUM(total_checks) AS total, "
            f"       SUM(available_checks) AS avail "
            f"FROM agg_osa_by_store "
            f"{where} "
            f"GROUP BY store_code, store_name "
            f"HAVING SUM(total_checks) >= {_MIN_CHECKS} "
            f"ORDER BY (SUM(available_checks)::float / NULLIF(SUM(total_checks),0)) {order}, "
            f"         SUM(total_checks) DESC "
            f"LIMIT 10"
        ),
        params,
    ).fetchall()

    return [
        {
            "store_name":      r[1] or "Unknown Store",
            "store_code":      r[0],
            "osa_percentage":  round(r[3] / r[2] * 100, 2) if r[2] else 0.0,
            "total_checks":    int(r[2] or 0),
            "available_checks": int(r[3] or 0),
        }
        for r in rows
    ]


@router.get("/osa-top-stores")
def get_osa_top_stores(
    country:      Optional[Union[str, list[str]]] = Query(None),
    channel:      Optional[Union[str, list[str]]] = Query(None),
    category:     Optional[Union[str, list[str]]] = Query(None),
    account:      Optional[Union[str, list[str]]] = Query(None),
    display_type: Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    country_list  = normalise_list(country)
    channel_list  = normalise_list(channel)
    category_list = normalise_list(category)
    account_list  = normalise_list(account)
    display_list  = normalise_list(display_type)
    cat_names     = resolve_category_names(db, category_list)

    cache_key = build_key(
        "osa_top_stores",
        country=country_list, channel=channel_list,
        category=cat_names, account=account_list,
        display_type=display_list,
        scope_countries=sorted(ctx.countries),
        scope_stores=sorted(ctx.stores),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    result = _query_stores(db, ctx, country_list, channel_list, cat_names, account_list, display_list, "DESC")
    set_cached(cache_key, result)
    return result


@router.get("/osa-bottom-stores")
def get_osa_bottom_stores(
    country:      Optional[Union[str, list[str]]] = Query(None),
    channel:      Optional[Union[str, list[str]]] = Query(None),
    category:     Optional[Union[str, list[str]]] = Query(None),
    account:      Optional[Union[str, list[str]]] = Query(None),
    display_type: Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    country_list  = normalise_list(country)
    channel_list  = normalise_list(channel)
    category_list = normalise_list(category)
    account_list  = normalise_list(account)
    display_list  = normalise_list(display_type)
    cat_names     = resolve_category_names(db, category_list)

    cache_key = build_key(
        "osa_bottom_stores",
        country=country_list, channel=channel_list,
        category=cat_names, account=account_list,
        display_type=display_list,
        scope_countries=sorted(ctx.countries),
        scope_stores=sorted(ctx.stores),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    result = _query_stores(db, ctx, country_list, channel_list, cat_names, account_list, display_list, "ASC")
    set_cached(cache_key, result)
    return result
