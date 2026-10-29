"""
Availability endpoints package.

Imports the single combined router so main.py only needs:
    from app.api.v1.endpoints.availability import router
"""
from app.api.v1.endpoints.availability.router import router

__all__ = ["router"]
