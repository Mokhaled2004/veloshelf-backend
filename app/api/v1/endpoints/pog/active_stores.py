"""GET /pog/active-stores — distinct store count from fact_osa_checks."""

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.pog.router import router


@router.get("/active-stores")
def get_active_stores(
    db:  Session     = Depends(get_db),
    ctx: UserContext = Depends(require_minimum_tier(5)),
):
    cache_key = build_key("pog_active_stores", scope_countries=sorted(ctx.countries))
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    where = ""
    params: dict = {}
    if not ctx.is_unrestricted and ctx.countries:
        where = "WHERE country_name = ANY(:scope_countries)"
        params["scope_countries"] = ctx.countries

    row = db.execute(
        text(
            f"SELECT COUNT(DISTINCT store_code) "
            f"FROM fact_osa_checks "
            f"{where}"
        ),
        params,
    ).fetchone()

    result = {"active_stores": int(row[0] or 0)}
    set_cached(cache_key, result)
    return result
