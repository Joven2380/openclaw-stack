from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.core.config import get_settings
from api.db.database import check_db_connection

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
    try:
        await check_db_connection()
        return JSONResponse({"status": "ready", "db": "ok"})
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "db": "error", "detail": str(e)},
        )
