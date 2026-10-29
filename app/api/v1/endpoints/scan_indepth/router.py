from fastapi import APIRouter

router = APIRouter(prefix="/scan", tags=["Scan Indepth"])

from app.api.v1.endpoints.scan_indepth import (  # noqa: E402, F401
    search,
    sku_detail,
    category_detail,
    store_detail,
)
