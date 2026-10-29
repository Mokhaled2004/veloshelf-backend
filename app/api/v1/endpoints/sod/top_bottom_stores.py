"""GET /sod/top-stores  +  GET /sod/bottom-stores"""

from typing import Optional, Union
from fastapi import Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.sod.filters import normalise_list, resolve_category_names, build_where
from app.api.v1.endpoints.sod.router import router

_MIN_RECORDS = 3


def _query(db, ctx, country_list, channel_list, cat_names, account_list, display_list, order):
    where, params = build_where(
        country=country_list, channel=channel_list,
        account=account_list, category_names=cat_names,
        display_type=display_list,
        scope_countries=ctx.countries, is_unrestricted=ctx.is_unrestricted,
    )
    rows = db.execute(
        text(f"SELECT store_name, SUM(row_count), SUM(sod_sum) "
             f"FROM agg_sod_by_store {where} "
             f"GROUP BY 1 HAVING SUM(row_count) >= {_MIN_RECORDS} "
             f"ORDER BY (SUM(sod_sum)/NULLIF(SUM(row_count),0)) {order}, "
             f"SUM(row_count) DESC LIMIT 10"),
        params,
    ).fetchall()
    return [{"store_name": r[0] or "Unknown Store",
             "sod_percentage": round(r[2]/r[1], 2) if r[1] else 0.0,
             "total_records": int(r[1] or 0)} for r in rows]


@router.get("/top-stores")
def get_sod_top_stores(
    country:      Optional[Union[str, list[str]]] = Query(None),
    channel:      Optional[Union[str, list[str]]] = Query(None),
    category:     Optional[Union[str, list[str]]] = Query(None),
    account:      Optional[Union[str, list[str]]] = Query(None),
    display_type: Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    cat_names = resolve_category_names(db, normalise_list(category))
    cache_key = build_key("sod_top_stores",
        country=normalise_list(country), channel=normalise_list(channel),
        category=cat_names, account=normalise_list(account),
        display_type=normalise_list(display_type), scope_countries=sorted(ctx.countries))
    cached = get_cached(cache_key)
    if cached is not None:
        return cached
    result = _query(db, ctx, normalise_list(country), normalise_list(channel),
                    cat_names, normalise_list(account), normalise_list(display_type), "DESC")
    set_cached(cache_key, result)
    return result


@router.get("/bottom-stores")
def get_sod_bottom_stores(
    country:      Optional[Union[str, list[str]]] = Query(None),
    channel:      Optional[Union[str, list[str]]] = Query(None),
    category:     Optional[Union[str, list[str]]] = Query(None),
    account:      Optional[Union[str, list[str]]] = Query(None),
    display_type: Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    cat_names = resolve_category_names(db, normalise_list(category))
    cache_key = build_key("sod_bottom_stores",
        country=normalise_list(country), channel=normalise_list(channel),
        category=cat_names, account=normalise_list(account),
        display_type=normalise_list(display_type), scope_countries=sorted(ctx.countries))
    cached = get_cached(cache_key)
    if cached is not None:
        return cached
    result = _query(db, ctx, normalise_list(country), normalise_list(channel),
                    cat_names, normalise_list(account), normalise_list(display_type), "ASC")
    set_cached(cache_key, result)
    return result
