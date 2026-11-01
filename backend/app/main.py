from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    ai,
    auth,
    dashboard,
    graph,
    health,
    listings,
    marketplace,
    organizations,
    pathways,
    requirements,
    symbiosis,
)
from app.core.config import get_settings
from app.core.error_handlers import register_exception_handlers

settings = get_settings()

app = FastAPI(title=settings.app_name, docs_url=f"{settings.api_prefix}/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix=settings.api_prefix, tags=["health"])
app.include_router(auth.router, prefix=settings.api_prefix, tags=["auth"])
app.include_router(organizations.router, prefix=settings.api_prefix, tags=["organizations"])
app.include_router(listings.router, prefix=settings.api_prefix, tags=["listings"])
app.include_router(marketplace.router, prefix=settings.api_prefix, tags=["marketplace"])
app.include_router(requirements.router, prefix=settings.api_prefix, tags=["requirements"])
app.include_router(dashboard.router, prefix=settings.api_prefix, tags=["dashboard"])
app.include_router(ai.router, prefix=settings.api_prefix, tags=["ai"])
app.include_router(graph.router, prefix=settings.api_prefix, tags=["graph"])
app.include_router(symbiosis.router, prefix=settings.api_prefix, tags=["symbiosis"])
app.include_router(pathways.router, prefix=settings.api_prefix, tags=["pathways"])

register_exception_handlers(app)
