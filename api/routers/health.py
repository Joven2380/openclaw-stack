import asyncpg
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.core.config import get_settings

router = APIRouter()


@router.get("/")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "env": settings.APP_ENV,
    }


@router.get("/ready")
async def ready() -> JSONResponse:
    settings = get_settings()

    # Strip SQLAlchemy dialect prefix — asyncpg only understands postgresql://
    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

    try:
        conn = await asyncpg.connect(db_url)
        await conn.execute("SELECT 1")
        await conn.close()
        return JSONResponse({"status": "ready", "db": "ok"})
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "db": "error", "detail": str(e)},
        )
