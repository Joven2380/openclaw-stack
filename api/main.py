import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.core.alerts import alert_error
from api.core.config import get_settings
from api.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(settings.LOG_LEVEL, settings.APP_ENV)
logger = get_logger(__name__)

# Production origins — update when domains are finalized
_PRODUCTION_ORIGINS = [
    "https://rpqtruckwide.com",
    "https://app.rpqtruckwide.com",
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("openclaw-stack started", version=settings.APP_VERSION, env=settings.APP_ENV)
    yield
    logger.info("openclaw-stack stopped")


app = FastAPI(
    title="openclaw-stack",
    version=settings.APP_VERSION,
    description="Multi-agent AI OS for RPQ Truckwide and agency work",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.APP_ENV == "development" else _PRODUCTION_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request logging middleware ────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next: Callable) -> JSONResponse:
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=duration_ms,
        )

# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    await alert_error(context=f"{request.method} {request.url.path}", error=exc)
    return JSONResponse(
        status_code=500,
        content={"error": "internal server error", "detail": str(exc)},
    )

# ── Routers ───────────────────────────────────────────────────────────────────

from api.routers import agents, health, webhooks  # noqa: E402

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(agents.router, prefix="/agents", tags=["agents"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
