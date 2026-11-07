from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.dependencies import CSRF_HEADER
from app.auth.router import router as auth_router
from app.core.config import get_settings
from app.integrations.router import router as integrations_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Shared API for the web and Windows desktop CBT applications. "
        "AI-generated assessment content must be grounded in approved school materials."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", CSRF_HEADER],
)


app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(integrations_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["operations"])
async def health_check() -> dict[str, str]:
    """Lightweight liveness endpoint; does not expose secrets or infrastructure details."""
    return {
        "status": "ok",
        "service": "intelligent-cbt-api",
        "version": settings.app_version,
    }


@app.get("/", tags=["operations"])
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "health": "/health",
    }
