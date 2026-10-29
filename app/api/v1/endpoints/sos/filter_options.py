"""GET /sos/filter-options"""

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.sos.router import router


@router.get("/filter-options")
def get_filter_options(
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    cache_key = build_key(
        "sos_filter_options",
        is_unrestricted=ctx.is_unrestricted,
        scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    clauses: list[str] = []
    params: dict = {}
    if not ctx.is_unrestricted and ctx.countries:
        clauses.append("country_name = ANY(:scope_countries)")
        params["scope_countries"] = ctx.countries

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    rows = db.execute(
        text(
            f"SELECT DISTINCT country_name, channel_name, account_name, display_type "
            f"FROM agg_sos_filter_options {where}"
        ),
        params,
    ).fetchall()

    countries     = sorted({r[0] for r in rows if r[0]})
    channels      = sorted({r[1] for r in rows if r[1]})
    accounts      = sorted({r[2] for r in rows if r[2]})
    display_types = sorted({r[3] for r in rows if r[3]})

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
