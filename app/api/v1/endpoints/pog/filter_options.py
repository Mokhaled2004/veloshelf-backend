"""
GET /pog/filter-options

Returns all distinct dropdown values sourced from agg_pog_filter_options
plus nestle_category labels from dim_category.
"""

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.pog.router import router


@router.get("/filter-options")
def get_pog_filter_options(
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    cache_key = build_key(
        "pog_filter_options",
        scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    # Scope restriction for non-unrestricted users
    scope_clause = ""
    params: dict = {}
    if not ctx.is_unrestricted and ctx.countries:
        scope_clause = "WHERE country_name = ANY(:scope_countries)"
        params["scope_countries"] = ctx.countries

    rows = db.execute(
        text(f"SELECT DISTINCT country_name, channel_name, customer_name, category_name "
             f"FROM agg_pog_filter_options {scope_clause} ORDER BY 1,2,3,4"),
        params,
    ).fetchall()

    countries  = sorted({r[0] for r in rows if r[0]})
    channels   = sorted({r[1] for r in rows if r[1]})
    customers  = sorted({r[2] for r in rows if r[2]})
    categories_raw = sorted({r[3] for r in rows if r[3]})

    # Translate raw category_name → nestle_category for the UI
    nestle_rows = db.execute(
        text("SELECT DISTINCT nestle_category FROM dim_category "
             "WHERE category_name = ANY(:cats) AND nestle_category IS NOT NULL"),
        {"cats": categories_raw},
    ).fetchall() if categories_raw else []
    nestle_categories = sorted({r[0] for r in nestle_rows if r[0]})

    result = {
        "countries":         countries,
        "channels":          channels,
        "customers":         customers,
        "categories":        nestle_categories,
    }
    set_cached(cache_key, result)
    return result
