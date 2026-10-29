"""
Shared APIRouter for all /sos/* endpoints.
All endpoint modules import this router and attach their routes to it.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/sos", tags=["Share of Shelf"])

# Import endpoint modules AFTER router is defined
from app.api.v1.endpoints.sos import (  # noqa: E402, F401
    filter_options,
    summary,
    by_country,
    by_channel,
    by_display_type,
    by_category,
    by_account,
    top_bottom_stores,
)
