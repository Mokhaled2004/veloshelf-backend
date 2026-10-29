"""Shared filter helpers for Share of Display aggregate tables."""

from typing import Optional, Union
from sqlalchemy import text
from sqlalchemy.orm import Session


def normalise_list(val: Optional[Union[str, list]]) -> list[str]:
    if not val:
        return []
    if isinstance(val, str):
        return [v.strip() for v in val.split(",") if v.strip()]
    return [str(v).strip() for v in val if str(v).strip()]


def resolve_category_names(db: Session, nestle_categories: list[str]) -> list[str]:
    if not nestle_categories:
        return []
    rows = db.execute(
        text("SELECT category_name FROM dim_category WHERE nestle_category = ANY(:cats)"),
        {"cats": nestle_categories},
    ).fetchall()
    return [r[0] for r in rows]


def build_where(
    *,
    country: list[str],
    channel: list[str],
    account: list[str],
    category_names: list[str],
    display_type: list[str],
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


def build_fact_where(
    *,
    country: list[str],
    channel: list[str],
    account: list[str],
    category_names: list[str],
    display_type: list[str],
    scope_countries: list[str],
    is_unrestricted: bool,
) -> tuple[str, dict]:
    """WHERE clause directly against fact_share_of_display columns."""
    return build_where(
        country=country, channel=channel, account=account,
        category_names=category_names, display_type=display_type,
        scope_countries=scope_countries, is_unrestricted=is_unrestricted,
    )
