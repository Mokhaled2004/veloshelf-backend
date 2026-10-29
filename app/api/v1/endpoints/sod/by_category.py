"""GET /sod/by-category — grouped by nestle_category"""

from typing import Optional, Union
from fastapi import Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.sod.filters import normalise_list, build_where
from app.api.v1.endpoints.sod.router import router


@router.get("/by-category")
def get_sod_by_category(
    country:      Optional[Union[str, list[str]]] = Query(None),
    channel:      Optional[Union[str, list[str]]] = Query(None),
    account:      Optional[Union[str, list[str]]] = Query(None),
    display_type: Optional[Union[str, list[str]]] = Query(None),
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    cache_key = build_key("sod_by_category",
        country=normalise_list(country), channel=normalise_list(channel),
        account=normalise_list(account), display_type=normalise_list(display_type),
        scope_countries=sorted(ctx.countries))
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    where, params = build_where(
        country=normalise_list(country), channel=normalise_list(channel),
        account=normalise_list(account), category_names=[],
        display_type=normalise_list(display_type),
        scope_countries=ctx.countries, is_unrestricted=ctx.is_unrestricted,
    )
    where_a = (where.replace("country_name", "a.country_name")
                    .replace("channel_name", "a.channel_name")
                    .replace("account_name", "a.account_name")
                    .replace("display_type",  "a.display_type")
                    .replace("category_name", "a.category_name"))

    rows = db.execute(
        text(f"SELECT dc.nestle_category, SUM(a.row_count), SUM(a.sod_sum) "
             f"FROM agg_sod_by_store a "
             f"JOIN dim_category dc ON dc.category_name = a.category_name "
             f"{where_a} GROUP BY 1 ORDER BY 1"),
        params,
    ).fetchall()

    result = [{"category": r[0] or "Unknown",
               "sod_percentage": round(r[2]/r[1], 2) if r[1] else 0.0,
               "total_records": int(r[1] or 0)} for r in rows]
    set_cached(cache_key, result)
    return result
