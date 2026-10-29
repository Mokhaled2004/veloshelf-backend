"""
GET /sod/summary — overall average SOD %

Queries fact_share_of_display directly (not the aggregate) so the number
always matches SELECT AVG(sod_pct) FROM fact_share_of_display exactly.
"""

from typing import Optional, Union

from fastapi import Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.sod.filters import normalise_list, resolve_category_names, build_fact_where
from app.api.v1.endpoints.sod.router import router


@router.get("/summary")
def get_sod_summary(
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
    cat_names     = resolve_category_names(db, normalise_list(category))
    account_list  = normalise_list(account)
    display_list  = normalise_list(display_type)

    cache_key = build_key(
        "sod_summary",
        country=country_list, channel=channel_list,
        category=cat_names, account=account_list,
        display_type=display_list, scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    where, params = build_fact_where(
        country=country_list, channel=channel_list,
        account=account_list, category_names=cat_names,
        display_type=display_list,
        scope_countries=ctx.countries, is_unrestricted=ctx.is_unrestricted,
    )

    row = db.execute(
        text(f"SELECT COUNT(*), AVG(sod_pct) FROM fact_share_of_display {where}"),
        params,
    ).fetchone()

    total = int(row[0] or 0)
    avg   = float(row[1] or 0)

    result = (
        {"sod_percentage": 0.0, "total_records": 0, "message": "No data found."}
        if total == 0
        else {"sod_percentage": round(avg, 2), "total_records": total,
              "user_tier": ctx.tier, "is_unrestricted": ctx.is_unrestricted}
    )
    set_cached(cache_key, result)
    return result
