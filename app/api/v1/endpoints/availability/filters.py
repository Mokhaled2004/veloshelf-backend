"""
Shared filter helpers for the availability aggregate tables.

Every endpoint calls `resolve_category_names()` once to translate the
incoming nestle_category filter values into raw category_name values
(the key stored in every agg table), then passes both lists to the
individual query helpers.

All helpers operate on plain SQLAlchemy Core text() queries via the
aggregate tables — no ORM scanning of fact_osa_checks at request time.
"""

from typing import Optional, Union
from sqlalchemy import text
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Value normalisation
# ---------------------------------------------------------------------------

def normalise_list(val: Optional[Union[str, list]]) -> list[str]:
    """Return a clean list of non-empty strings from a multi-value param."""
    if not val:
        return []
    if isinstance(val, str):
        return [v.strip() for v in val.split(",") if v.strip()]
    return [str(v).strip() for v in val if str(v).strip()]


# ---------------------------------------------------------------------------
# Category resolution: nestle_category → raw category_name list
# ---------------------------------------------------------------------------

def resolve_category_names(
    db: Session,
    nestle_categories: list[str],
) -> list[str]:
    """
    Given a list of nestle_category values (what the UI sends), return the
    corresponding raw category_name values stored in the agg tables.
    Returns an empty list when nestle_categories is empty (= no filter).
    """
    if not nestle_categories:
        return []
    rows = db.execute(
        text(
            "SELECT category_name FROM dim_category "
            "WHERE nestle_category = ANY(:cats)"
        ),
        {"cats": nestle_categories},
    ).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Generic WHERE clause builder for aggregate tables
# ---------------------------------------------------------------------------

def build_where(
    *,
    country: list[str],
    channel: list[str],
    customer: list[str],
    category_names: list[str],   # raw category_name values (already resolved)
    display_type: list[str],
    # scope restrictions from UserContext (already resolved list of strings)
    scope_countries: list[str],
    scope_stores: list[str],     # store-level scope maps to customer_name here
    is_unrestricted: bool,
) -> tuple[str, dict]:
    """
    Build a parameterised WHERE clause fragment and accompanying bind dict.
    Returns ("WHERE ...", {params}) or ("", {}) when nothing to filter.
    """
    clauses: list[str] = []
    params: dict = {}

    # ---- User scope --------------------------------------------------------
    if not is_unrestricted:
        if scope_stores:
            # Store-scope users: restrict by store_code in agg_osa_by_store,
            # but agg_osa_by_country / channel etc. do not carry store_code.
            # We leave scope_stores to be handled by the per-endpoint query
            # directly; skip here (the endpoint will add its own clause).
            pass
        elif scope_countries:
            clauses.append("country_name = ANY(:scope_countries)")
            params["scope_countries"] = scope_countries

    # ---- Explicit user filters --------------------------------------------
    if country:
        clauses.append("country_name = ANY(:country)")
        params["country"] = country

    if channel:
        clauses.append("channel_name = ANY(:channel)")
        params["channel"] = channel

    if customer:
        clauses.append("customer_name = ANY(:customer)")
        params["customer"] = customer

    if category_names:
        clauses.append("category_name = ANY(:category_names)")
        params["category_names"] = category_names

    if display_type:
        clauses.append("display_type = ANY(:display_type)")
        params["display_type"] = display_type

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params
