"""GET /sos/by-category — grouped by nestle_category"""

from typing import Optional, Union

from fastapi import Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.sos.filters import normalise_list, build_where
from app.api.v1.endpoints.sos.router import router


@router.get("/by-category")
def get_sos_by_category(
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
        "sos_by_category",
        country=country_list, channel=channel_list,
        account=account_list, display_type=display_list,
        scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    where, params = build_where(
        country=country_list, channel=channel_list,
        account=account_list, category_names=[],
        display_type=display_list,
        scope_countries=ctx.countries,
        is_unrestricted=ctx.is_unrestricted,
    )

    # Prefix columns with alias to avoid ambiguity after JOIN
    where_a = where.replace("country_name", "a.country_name") \
                   .replace("channel_name", "a.channel_name") \
                   .replace("account_name", "a.account_name") \
                   .replace("display_type",  "a.display_type") \
                   .replace("category_name", "a.category_name")

    rows = db.execute(
        text(
            f"SELECT dc.nestle_category, SUM(a.row_count), SUM(a.sos_sum) "
            f"FROM agg_sos_by_store a "
            f"JOIN dim_category dc ON dc.category_name = a.category_name "
            f"{where_a} "
            f"GROUP BY dc.nestle_category "
            f"ORDER BY dc.nestle_category"
        ),
        params,
    ).fetchall()

    result = [
        {
            "category":       r[0] or "Unknown",
            "sos_percentage": round(r[2] / r[1], 2) if r[1] else 0.0,
            "total_records":  int(r[1] or 0),
        }
        for r in rows
    ]
    set_cached(cache_key, result)
    return result
