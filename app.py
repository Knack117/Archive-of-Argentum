"""FastAPI application entry point for Archive of Argentum."""
import logging
import os
import time
import uvicorn
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi

from aoa.constants import API_VERSION
from config import settings
from aoa.models import DeckCard, DeckValidationRequest, DeckValidationResponse
from aoa.routes import cards, cedh, commanders, combos, deck_validation, popular_decks, system, themes
from aoa.routes.deck_validation import (
    COMMANDER_BRACKETS,
    EARLY_GAME_COMBOS,
    GAME_CHANGERS,
    MASS_LAND_DENIAL,
    DeckValidator,
)
from aoa.routes.themes import (
    _build_theme_route_candidates,
    _create_categories_summary,
    _estimate_response_size,
    _generate_card_limit_plan,
    _parse_theme_slugs_from_html,
    _split_color_prefixed_theme_slug,
    _split_theme_slug,
    _resolve_theme_card_limit,
    _validate_theme_slug_against_catalog,
    extract_theme_sections_from_json,
    normalize_theme_colors,
)
from aoa.services.commanders import (
    extract_commander_name_from_url,
    extract_commander_summary_data,
    normalize_commander_name,
    scrape_edhrec_commander_page,
)

# Configure logging FIRST (before creating FastAPI app)
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),  # Ensure logs go to stdout for Render
    ]
)

# Set uvicorn logging level too
uvicorn_logger = logging.getLogger("uvicorn")
uvicorn_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

app = FastAPI(
    title="MTG Deckbuilding API",
    description="Commander utility endpoints including deck validation and EDHRec tooling.",
    version=API_VERSION,
)

MAX_OPENAPI_OPERATIONS = 30
PRIORITIZED_OPENAPI_PATHS = [
    "/api/v1/cards/search",
    "/api/v1/cards/autocomplete",
    "/api/v1/cards/random",
    "/api/v1/cards/gamechangers",
    "/api/v1/cards/banned",
    "/api/v1/cards/mass-land-destruction",
    "/api/v1/cards/{card_id}",
    "/api/v1/commander/summary",
    "/api/v1/combos/commander/{commander_name}",
    "/api/v1/combos/search",
    "/api/v1/combos/early-game",
    "/api/v1/combos/late-game",
    "/api/v1/combos/info",
    "/api/v1/tags/available",
    "/api/v1/themes/{theme_slug}",
    "/api/v1/tags/catalog",
    "/api/v1/deck/commander-salt/{commander_name}",
    "/api/v1/deck/validate",
    "/api/v1/brackets/info",
    "/api/v1/salt/info",
    "/api/v1/deck/check-early-game-combos",
    "/api/v1/deck/check-late-game-combos",
    "/api/v1/deck/check-all-combos",
    "/api/v1/popular-decks",
    "/api/v1/popular-decks/info",
    "/api/v1/popular-decks/{bracket}",
    "/api/v1/cedh/search",
    "/api/v1/cedh/commanders",
    "/api/v1/cedh/stats",
    "/api/v1/cedh/info",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with timing and response status."""
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    
    # Log request details
    logger = logging.getLogger("aoa.access")
    logger.info(
        f"{request.client.host} {request.method} {request.url.path} "
        f"-> {response.status_code} ({process_time:.1f}ms)"
    )
    
    return response

app.include_router(system.router)
app.include_router(cards.router)
app.include_router(commanders.router)
app.include_router(combos.router)
app.include_router(themes.router)
app.include_router(deck_validation.router)
app.include_router(popular_decks.router)
app.include_router(cedh.router)


def _limit_openapi_paths(openapi_schema: dict) -> None:
    """Restrict the number of OpenAPI operations to the configured maximum."""

    paths = openapi_schema.get("paths", {})
    if not paths:
        return

    operation_count = sum(len(methods) for methods in paths.values())
    if operation_count <= MAX_OPENAPI_OPERATIONS:
        return

    allowed_paths = []
    for prioritized_path in PRIORITIZED_OPENAPI_PATHS:
        if prioritized_path in paths:
            allowed_paths.append(prioritized_path)
        if len(allowed_paths) >= MAX_OPENAPI_OPERATIONS:
            break

    if len(allowed_paths) < MAX_OPENAPI_OPERATIONS:
        for path in paths:
            if path in allowed_paths:
                continue
            allowed_paths.append(path)
            if len(allowed_paths) >= MAX_OPENAPI_OPERATIONS:
                break

    openapi_schema["paths"] = {path: paths[path] for path in allowed_paths if path in paths}


def custom_openapi():
    """Generate OpenAPI schema with consistent security defaults."""
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=API_VERSION,
        description=app.description,
        routes=app.routes,
    )

    servers = openapi_schema.setdefault("servers", [])
    render_server = {
        "url": "https://mtg-mightstone-gpt.onrender.com",
        "description": "Render production deployment",
    }
    if render_server not in servers:
        servers.append(render_server)

    security_schemes = openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    security_schemes.setdefault(
        "HTTPBearer",
        {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "API Key",
            "description": "All endpoints (except status, health, and root) require a Bearer API key.",
        },
    )

    unsecured_paths = {"/", "/health", "/api/v1/status"}
    for path, methods in openapi_schema.get("paths", {}).items():
        if path in unsecured_paths:
            continue
        for method in methods.values():
            method.setdefault("security", [{"HTTPBearer": []}])

    _limit_openapi_paths(openapi_schema)

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

__all__ = [
    "app",
    "DeckValidator",
    "DeckValidationRequest",
    "DeckValidationResponse",
    "DeckCard",
    "COMMANDER_BRACKETS",
    "MASS_LAND_DENIAL",
    "GAME_CHANGERS",
    "EARLY_GAME_COMBOS",
    "scrape_edhrec_commander_page",
    "extract_commander_name_from_url",
    "normalize_commander_name",
    "extract_commander_summary_data",
    "_build_theme_route_candidates",
    "_resolve_theme_card_limit",
    "_estimate_response_size",
    "_create_categories_summary",
    "_generate_card_limit_plan",
    "_parse_theme_slugs_from_html",
    "_split_color_prefixed_theme_slug",
    "_split_theme_slug",
    "_validate_theme_slug_against_catalog",
    "extract_theme_sections_from_json",
    "normalize_theme_colors",
]


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Return consistent HTTP error responses."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.status_code,
                "message": exc.detail,
                "timestamp": datetime.utcnow().isoformat(),
            }
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler to avoid leaking stack traces."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": 500,
                "message": "Internal server error",
                "timestamp": datetime.utcnow().isoformat(),
            }
        },
    )


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        reload=False,
        log_level=settings.log_level.lower(),
    )
