from fastapi import APIRouter

router = APIRouter(prefix="/sod", tags=["Share of Display"])

from app.api.v1.endpoints.sod import (  # noqa: E402, F401
    filter_options,
    summary,
    by_country,
    by_channel,
    by_display_type,
    by_category,
    by_account,
    top_bottom_stores,
)
