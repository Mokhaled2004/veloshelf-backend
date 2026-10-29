"""
Shared APIRouter instance for all /availability/* endpoints.

All endpoint modules import this router and register their routes on it.
The package __init__.py re-exports it so main.py only needs:

    from app.api.v1.endpoints.availability import router
"""

from fastapi import APIRouter

router = APIRouter(prefix="/availability", tags=["Availability"])

# -----------------------------------------------------------------
# Import endpoint modules AFTER the router is defined so that the
# @router.get decorators in each module attach to this instance.
# -----------------------------------------------------------------
from app.api.v1.endpoints.availability import (  # noqa: E402, F401
    filter_options,
    summary,
    by_country,
    by_channel,
    by_display_type,
    by_category,
    by_account,
    top_bottom_stores,
    top_bottom_skus,
)
