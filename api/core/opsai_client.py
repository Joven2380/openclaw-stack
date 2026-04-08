"""Async HTTP client for OPS-AI API.

All Jake tools that need fleet/business data go through here.
Auth: X-Bot-Key header, value from OPSAI_API_KEY env var.
"""

from __future__ import annotations

import httpx

from api.core.config import get_settings
from api.core.logging import get_logger

log = get_logger(__name__)

_TIMEOUT = 15.0  # seconds


def _client() -> httpx.AsyncClient:
    settings = get_settings()
    if not settings.OPSAI_API_URL:
        raise RuntimeError("OPSAI_API_URL is not configured — set it in .env")
    if not settings.OPSAI_API_KEY:
        raise RuntimeError("OPSAI_API_KEY is not configured — set it in .env")
    return httpx.AsyncClient(
        base_url=settings.OPSAI_API_URL,
        headers={"X-Bot-Key": settings.OPSAI_API_KEY, "Accept": "application/json"},
        timeout=_TIMEOUT,
        follow_redirects=True,
    )


async def opsai_get(path: str, params: dict | None = None) -> dict:
    """GET from OPS-AI API. Path like '/api/v1/trips'."""
    async with _client() as client:
        settings = get_settings()
        full_url = f"{settings.OPSAI_API_URL.rstrip('/')}/{path.lstrip('/')}"
        log.info("opsai_get", url=full_url, params=params)
        try:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            log.error(
                "opsai_get_http_error",
                url=full_url,
                status=exc.response.status_code,
                body=exc.response.text[:500],
            )
            return {
                "error": f"OPS-AI returned {exc.response.status_code}",
                "detail": exc.response.text[:500],
            }
        except httpx.TimeoutException:
            log.error("opsai_get_timeout", url=full_url)
            return {"error": "OPS-AI request timed out after 15s"}
        except Exception as exc:
            log.error("opsai_get_failed", url=full_url, error=str(exc))
            return {"error": str(exc)}


async def opsai_post(path: str, body: dict | None = None) -> dict:
    """POST to OPS-AI API."""
    async with _client() as client:
        log.info("opsai_post", path=path)
        try:
            resp = await client.post(path, json=body or {})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            log.error("opsai_post_http_error", path=path, status=exc.response.status_code)
            return {
                "error": f"OPS-AI returned {exc.response.status_code}",
                "detail": exc.response.text[:500],
            }
        except httpx.TimeoutException:
            log.error("opsai_post_timeout", path=path)
            return {"error": "OPS-AI request timed out after 15s"}
        except Exception as exc:
            log.error("opsai_post_failed", path=path, error=str(exc))
            return {"error": str(exc)}
