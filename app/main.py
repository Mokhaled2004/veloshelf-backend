from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.database import SessionLocal, engine, Base
from app.core.security import get_password_hash
from app.models.user import User

# Routers
from app.api.v1.endpoints import auth, users, metrics
from app.api.v1.endpoints.availability import router as availability_router
from app.api.v1.endpoints.sos import router as sos_router
from app.api.v1.endpoints.sod import router as sod_router
from app.api.v1.endpoints.pog import router as pog_router
from app.api.v1.endpoints.scan_indepth import router as scan_router
from app.api.v1.endpoints.aggregate_refresh import router as aggregate_refresh_router

# Initialise ORM-managed tables (auth, scope, etc.)
# The main fact/dim/agg tables are created via SQL migration files.
Base.metadata.create_all(bind=engine)

app = FastAPI(title="VeloShelf Backend API", version="1.0.0")

# ---------------------------------------------------------------------------
# CORS — allow the Next.js dev server and any deployed origin.
# IMPORTANT: CORSMiddleware must be added BEFORE the exception handler so
# that the Access-Control-Allow-Origin header is present even on 4xx/5xx
# responses; otherwise browsers report "Failed to fetch" instead of the
# real HTTP error.
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Global HTTP exception handler — ensures CORS headers survive 401/403/etc.
# Without this, Starlette's default exception handler returns the error
# response before the CORS middleware can inject its headers, causing the
# browser to see a CORS failure instead of the actual status code.
# ---------------------------------------------------------------------------
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers={
            "Access-Control-Allow-Origin":      request.headers.get("origin", "*"),
            "Access-Control-Allow-Credentials": "true",
        },
    )

# ---------------------------------------------------------------------------
# Startup: ensure a default GM/admin account always exists
# ---------------------------------------------------------------------------
@app.on_event("startup")
def seed_default_admin() -> None:
    db = SessionLocal()
    try:
        admin_exists = db.query(User).filter(User.tier == 1).first()
        if not admin_exists:
            default_admin = User(
                username="gm.demo",
                password_hash=get_password_hash("ChangeMe123!"),
                tier=1,
                is_active=True,
            )
            db.add(default_admin)
            db.commit()
            print("Seeded default demo user: gm.demo")
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth.router,              prefix="/api/v1")
app.include_router(users.router,             prefix="/api/v1")
app.include_router(metrics.router,           prefix="/api/v1")
app.include_router(availability_router,      prefix="/api/v1")
app.include_router(sos_router,               prefix="/api/v1")
app.include_router(sod_router,               prefix="/api/v1")
app.include_router(pog_router,               prefix="/api/v1")
app.include_router(scan_router,              prefix="/api/v1")
app.include_router(aggregate_refresh_router, prefix="/api/v1")

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/")
def root():
    return {"message": "VeloShelf Backend API — Running & Secured."}
