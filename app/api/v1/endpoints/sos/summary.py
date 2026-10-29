"""GET /sos/summary — overall average SOS %

Queries fact_share_of_shelf directly (not the aggregate) so the number
always matches SELECT AVG(sos_pct) FROM fact_share_of_shelf with the same
filters applied.  A straight AVG on one numeric column is fast even on
millions of rows — PostgreSQL needs no grouping, just a seq scan.
"""

from typing import Optional, Union

from fastapi import Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.sos.filters import normalise_list, resolve_category_names
from app.api.v1.endpoints.sos.router import router


def _build_fact_where(
    *,
    country: list[str],
    channel: list[str],
    account: list[str],
    category_names: list[str],
    display_type: list[str],
    scope_countries: list[str],
    is_unrestricted: bool,
) -> tuple[str, dict]:
    """WHERE clause directly against fact_share_of_shelf columns."""
    clauses: list[str] = []
    params: dict = {}

    if not is_unrestricted and scope_countries:
        clauses.append("country_name = ANY(:scope_countries)")
        params["scope_countries"] = scope_countries

    if country:
        clauses.append("country_name = ANY(:country)")
        params["country"] = country
    if channel:
        clauses.append("channel_name = ANY(:channel)")
        params["channel"] = channel
    if account:
        clauses.append("account_name = ANY(:account)")
        params["account"] = account
    if category_names:
        clauses.append("category_name = ANY(:category_names)")
        params["category_names"] = category_names
    if display_type:
        clauses.append("display_type = ANY(:display_type)")
        params["display_type"] = display_type

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


@router.get("/summary")
def get_sos_summary(
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
        "sos_summary",
        country=country_list, channel=channel_list,
        category=cat_names, account=account_list,
        display_type=display_list,
        scope_countries=sorted(ctx.countries),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    # Query the raw fact table — guarantees AVG matches direct SQL query
    where, params = _build_fact_where(
        country=country_list, channel=channel_list,
        account=account_list, category_names=cat_names,
        display_type=display_list,
        scope_countries=ctx.countries,
        is_unrestricted=ctx.is_unrestricted,
    )

    row = db.execute(
        text(
            f"SELECT COUNT(*), AVG(sos_pct) "
            f"FROM fact_share_of_shelf {where}"
        ),
        params,
    ).fetchone()

    total_rows = int(row[0] or 0)
    avg_sos    = float(row[1] or 0)

    if total_rows == 0:
        result = {
            "sos_percentage": 0.0,
            "total_records":  0,
            "message": "No data found within your assigned scope.",
        }
    else:
        result = {
            "sos_percentage":  round(avg_sos, 2),
            "total_records":   total_rows,
            "user_tier":       ctx.tier,
            "is_unrestricted": ctx.is_unrestricted,
        }

    set_cached(cache_key, result)
    return result
