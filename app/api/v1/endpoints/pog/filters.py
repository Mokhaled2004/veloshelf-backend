"""
Shared filter helpers for POG Compliance aggregate tables.

agg_pog_by_store columns used for filtering:
  country_name, channel_name, customer_name, category_name, brand_name
"""

from typing import Optional, Union
from sqlalchemy import text
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Value normalisation (identical to every other section)
# ---------------------------------------------------------------------------

def normalise_list(val: Optional[Union[str, list]]) -> list[str]:
    if not val:
        return []
    if isinstance(val, str):
        return [v.strip() for v in val.split(",") if v.strip()]
    return [str(v).strip() for v in val if str(v).strip()]


# ---------------------------------------------------------------------------
# Translate nestle_category UI labels → raw category_name values
# ---------------------------------------------------------------------------

def resolve_category_names(db: Session, nestle_categories: list[str]) -> list[str]:
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
# WHERE clause builder for agg_pog_by_store
# ---------------------------------------------------------------------------

def build_where(
    *,
    country: list[str],
    channel: list[str],
    customer: list[str],
    category_names: list[str],
    brand: list[str],
    scope_countries: list[str],
    is_unrestricted: bool,
) -> tuple[str, dict]:
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

    if customer:
        clauses.append("customer_name = ANY(:customer)")
        params["customer"] = customer

    if category_names:
        clauses.append("category_name = ANY(:category_names)")
        params["category_names"] = category_names

    if brand:
        clauses.append("brand_name = ANY(:brand)")
        params["brand"] = brand

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params
