from fastapi import APIRouter

router = APIRouter(prefix="/pog", tags=["Planogram Compliance"])

# endpoint modules are imported for their side-effects (they call @router.get)
from app.api.v1.endpoints.pog import (  # noqa: E402, F401
    filter_options,
    summary,
    by_country,
    by_channel,
    by_category,
    by_brand,
    top_bottom_stores,
    low_compliant,
    active_stores,
)
