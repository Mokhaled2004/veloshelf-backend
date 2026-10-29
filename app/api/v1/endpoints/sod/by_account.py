"""GET /sod/by-account"""

from typing import Optional, Union
from fastapi import Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.sod.filters import normalise_list, resolve_category_names, build_where
from app.api.v1.endpoints.sod.router import router


@router.get("/by-account")
def get_sod_by_account(
    country:      Optional[Union[str, list[str]]] = Query(None),
    channel:      Optional[Union[str, list[str]]] = Query(None),
    category:     Optional[Union[str, list[str]]] = Query(None),
    display_type: Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    cat_names = resolve_category_names(db, normalise_list(category))
    cache_key = build_key("sod_by_account",
        country=normalise_list(country), channel=normalise_list(channel),
        category=cat_names, display_type=normalise_list(display_type),
        scope_countries=sorted(ctx.countries))
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    where, params = build_where(
        country=normalise_list(country), channel=normalise_list(channel),
        account=[], category_names=cat_names,
        display_type=normalise_list(display_type),
        scope_countries=ctx.countries, is_unrestricted=ctx.is_unrestricted,
    )
    rows = db.execute(
        text(f"SELECT account_name, SUM(row_count), SUM(sod_sum) "
             f"FROM agg_sod_by_store {where} "
             f"GROUP BY 1 ORDER BY SUM(row_count) DESC"),
        params,
    ).fetchall()

    result = [{"account": r[0] or "Unknown Account",
               "sod_percentage": round(r[2]/r[1], 2) if r[1] else 0.0,
               "total_records": int(r[1] or 0)} for r in rows]
    set_cached(cache_key, result)
    return result
