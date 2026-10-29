"""
GET /availability/filter-options

Returns the five dropdown lists for the UI filters.
Reads from agg_osa_filter_options (tiny table) + dim_category (tiny).
Cached in Redis for AVAILABILITY_CACHE_TTL seconds.
"""

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.availability.router import router


@router.get("/filter-options")
def get_filter_options(
    db: Session = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    cache_key = build_key(
        "filter_options",
        is_unrestricted=ctx.is_unrestricted,
        scope_countries=sorted(ctx.countries),
        scope_stores=sorted(ctx.stores),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    # ------------------------------------------------------------------
    # Scope WHERE for agg_osa_filter_options
    # ------------------------------------------------------------------
    clauses: list[str] = []
    params: dict = {}

    if not ctx.is_unrestricted:
        if ctx.stores:
            # Store-scoped: pull allowed customer names from agg_osa_by_store
            store_rows = db.execute(
                text(
                    "SELECT DISTINCT customer_name FROM agg_osa_by_store "
                    "WHERE store_code = ANY(:stores)"
                ),
                {"stores": ctx.stores},
            ).fetchall()
            allowed_customers = [r[0] for r in store_rows if r[0]]
            if allowed_customers:
                clauses.append("customer_name = ANY(:allowed_customers)")
                params["allowed_customers"] = allowed_customers
        elif ctx.countries:
            clauses.append("country_name = ANY(:scope_countries)")
            params["scope_countries"] = ctx.countries

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    rows = db.execute(
        text(f"SELECT DISTINCT country_name, channel_name, customer_name, display_type "
             f"FROM agg_osa_filter_options {where}"),
        params,
    ).fetchall()

    countries   = sorted({r[0] for r in rows if r[0]})
    channels    = sorted({r[1] for r in rows if r[1]})
    accounts    = sorted({r[2] for r in rows if r[2]})
    display_types = sorted({r[3] for r in rows if r[3]})

    # nestle_category comes from dim_category (tiny, no scope needed)
    cat_rows = db.execute(
        text("SELECT DISTINCT nestle_category FROM dim_category WHERE nestle_category IS NOT NULL ORDER BY 1")
    ).fetchall()
    categories = [r[0] for r in cat_rows]

    result = {
        "countries":     countries,
        "channels":      channels,
        "categories":    categories,
        "accounts":      accounts,
        "display_types": display_types,
    }
    set_cached(cache_key, result)
    return result
