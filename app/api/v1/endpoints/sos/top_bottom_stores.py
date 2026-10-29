"""
GET /sos/top-stores
GET /sos/bottom-stores

Ranked by average SOS %; minimum 3 records to qualify.
"""

from typing import Optional, Union

from fastapi import Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.sos.filters import normalise_list, resolve_category_names, build_where
from app.api.v1.endpoints.sos.router import router

_MIN_RECORDS = 3


def _query_stores(
    db: Session,
    ctx: UserContext,
    country_list: list[str],
    channel_list: list[str],
    cat_names: list[str],
    account_list: list[str],
    display_list: list[str],
    order: str,
) -> list[dict]:
    where, params = build_where(
        country=country_list, channel=channel_list,
        account=account_list, category_names=cat_names,
        display_type=display_list,
        scope_countries=ctx.countries,
        is_unrestricted=ctx.is_unrestricted,
    )

    rows = db.execute(
        text(
            f"SELECT store_name, SUM(row_count), SUM(sos_sum) "
            f"FROM agg_sos_by_store {where} "
            f"GROUP BY store_name "
            f"HAVING SUM(row_count) >= {_MIN_RECORDS} "
            f"ORDER BY (SUM(sos_sum) / NULLIF(SUM(row_count), 0)) {order}, "
            f"         SUM(row_count) DESC "
            f"LIMIT 10"
        ),
        params,
    ).fetchall()

    return [
        {
            "store_name":     r[0] or "Unknown Store",
            "sos_percentage": round(r[2] / r[1], 2) if r[1] else 0.0,
            "total_records":  int(r[1] or 0),
        }
        for r in rows
    ]


@router.get("/top-stores")
def get_sos_top_stores(
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
        "sos_top_stores",
        country=country_list, channel=channel_list,
        category=cat_names, account=account_list,
        display_type=display_list,
        scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    result = _query_stores(db, ctx, country_list, channel_list, cat_names, account_list, display_list, "DESC")
    set_cached(cache_key, result)
    return result


@router.get("/bottom-stores")
def get_sos_bottom_stores(
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
        "sos_bottom_stores",
        country=country_list, channel=channel_list,
        category=cat_names, account=account_list,
        display_type=display_list,
        scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    result = _query_stores(db, ctx, country_list, channel_list, cat_names, account_list, display_list, "ASC")
    set_cached(cache_key, result)
    return result
