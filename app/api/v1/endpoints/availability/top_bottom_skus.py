"""
GET /availability/osa-top-skus
GET /availability/osa-bottom-skus

Top SKUs by OSA %; bottom SKUs by zero-count (most out-of-stock occurrences).
Both read from agg_osa_by_sku.  Bottom-SKUs also pulls from
agg_osa_sku_zero_stores to show the stores modal.
"""

from typing import Optional, Union

from fastapi import Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import UserContext, require_minimum_tier
from app.core.cache import build_key, get_cached, set_cached
from app.api.v1.endpoints.availability.filters import (
    normalise_list, resolve_category_names, build_where,
)
from app.api.v1.endpoints.availability.router import router

_MIN_CHECKS = 5


def _sku_where(
    db: Session,
    ctx: UserContext,
    country_list: list[str],
    channel_list: list[str],
    cat_names: list[str],
    account_list: list[str],
    display_list: list[str],
    table_alias: str = "",
) -> tuple[str, dict]:
    prefix = f"{table_alias}." if table_alias else ""

    where, params = build_where(
        country=country_list, channel=channel_list,
        customer=account_list, category_names=cat_names,
        display_type=display_list,
        scope_countries=ctx.countries,
        scope_stores=ctx.stores,
        is_unrestricted=ctx.is_unrestricted,
    )

    # Re-prefix column names when using a table alias
    if table_alias and where:
        for col in ("country_name", "channel_name", "customer_name", "category_name", "display_type"):
            where = where.replace(f" {col}", f" {prefix}{col}") \
                         .replace(f"({col}", f"({prefix}{col}")

    return where, params


@router.get("/osa-top-skus")
def get_osa_top_skus(
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
        "osa_top_skus",
        country=country_list, channel=channel_list,
        category=cat_names, account=account_list,
        display_type=display_list,
        scope_countries=sorted(ctx.countries),
        scope_stores=sorted(ctx.stores),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    where, params = build_where(
        country=country_list, channel=channel_list,
        customer=account_list, category_names=cat_names,
        display_type=display_list,
        scope_countries=ctx.countries,
        scope_stores=ctx.stores,
        is_unrestricted=ctx.is_unrestricted,
    )

    rows = db.execute(
        text(
            f"SELECT sap_code, sku_name, "
            f"       SUM(total_checks) AS total, "
            f"       SUM(available_checks) AS avail "
            f"FROM agg_osa_by_sku "
            f"{where} "
            f"GROUP BY sap_code, sku_name "
            f"HAVING SUM(total_checks) >= {_MIN_CHECKS} "
            f"ORDER BY (SUM(available_checks)::float / NULLIF(SUM(total_checks),0)) DESC, "
            f"         SUM(total_checks) DESC "
            f"LIMIT 10"
        ),
        params,
    ).fetchall()

    result = [
        {
            "sku_name":        r[1] or "Unknown SKU",
            "sap_code":        r[0],
            "osa_percentage":  round(r[3] / r[2] * 100, 2) if r[2] else 0.0,
            "total_checks":    int(r[2] or 0),
            "available_checks": int(r[3] or 0),
        }
        for r in rows
    ]
    set_cached(cache_key, result)
    return result


@router.get("/osa-bottom-skus")
def get_osa_bottom_skus(
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
        "osa_bottom_skus",
        country=country_list, channel=channel_list,
        category=cat_names, account=account_list,
        display_type=display_list,
        scope_countries=sorted(ctx.countries),
        scope_stores=sorted(ctx.stores),
    )
    cached = get_cached(cache_key)
    if cached is not None:
        return cached

    # ---- Top zero-count SKUs -----------------------------------------------
    where, params = build_where(
        country=country_list, channel=channel_list,
        customer=account_list, category_names=cat_names,
        display_type=display_list,
        scope_countries=ctx.countries,
        scope_stores=ctx.stores,
        is_unrestricted=ctx.is_unrestricted,
    )

    sku_rows = db.execute(
        text(
            f"SELECT sap_code, sku_name, "
            f"       SUM(total_checks) AS total, "
            f"       SUM(available_checks) AS avail, "
            f"       SUM(total_checks) - SUM(available_checks) AS zeros "
            f"FROM agg_osa_by_sku "
            f"{where} "
            f"GROUP BY sap_code, sku_name "
            f"HAVING (SUM(total_checks) - SUM(available_checks)) > 0 "
            f"ORDER BY zeros DESC, total DESC "
            f"LIMIT 10"
        ),
        params,
    ).fetchall()

    if not sku_rows:
        result = {"items": [], "total": 0}
        set_cached(cache_key, result)
        return result

    sap_codes = [r[0] for r in sku_rows if r[0]]

    # ---- Stores with zeros for these SKUs ----------------------------------
    zs_where, zs_params = build_where(
        country=country_list, channel=channel_list,
        customer=account_list, category_names=cat_names,
        display_type=display_list,
        scope_countries=ctx.countries,
        scope_stores=ctx.stores,
        is_unrestricted=ctx.is_unrestricted,
    )
    zs_params["_sap_codes"] = sap_codes
    sap_clause = "sap_code = ANY(:_sap_codes)"
    zs_where = f"{zs_where} AND {sap_clause}" if zs_where else f"WHERE {sap_clause}"

    store_rows = db.execute(
        text(
            f"SELECT DISTINCT sap_code, store_name "
            f"FROM agg_osa_sku_zero_stores "
            f"{zs_where} "
            f"ORDER BY sap_code, store_name"
        ),
        zs_params,
    ).fetchall()

    sku_stores_map: dict[str, list[str]] = {}
    for sap, sname in store_rows:
        sku_stores_map.setdefault(sap, []).append(sname)

    items = [
        {
            "sku_name":        r[1] or "Unknown SKU",
            "sap_code":        r[0],
            "zero_count":      int(r[4] or 0),
            "osa_percentage":  round(r[3] / r[2] * 100, 2) if r[2] else 0.0,
            "total_checks":    int(r[2] or 0),
            "available_checks": int(r[3] or 0),
            "store_names":     sku_stores_map.get(r[0], []),
        }
        for r in sku_rows
    ]

    result = {"items": items, "total": len(items)}
    set_cached(cache_key, result)
    return result
