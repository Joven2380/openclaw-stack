import time

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.core.alerts import alert_error
from api.core.cost_calc import compute_cost
from api.core.logging import get_logger
from api.core.model_clients import call_model
from api.core.model_router import classify_task, get_model_config
from api.db.database import get_db
from api.db.queries import log_task
from api.models.schemas import AgentRunRequest, AgentRunResponse

router = APIRouter()
logger = get_logger(__name__)


class ClassifyRequest(BaseModel):
    message: str


class ClassifyResponse(BaseModel):
    task_type: str
    model: str
    provider: str
    max_tokens: int


@router.post("/classify", response_model=ClassifyResponse)
async def classify(request: ClassifyRequest) -> ClassifyResponse:
    """Classifies a message and returns routing info without calling a model."""
    task_type = await classify_task(request.message)
    config = get_model_config(task_type)
    return ClassifyResponse(
        task_type=task_type.value,
        model=config.model,
        provider=config.provider,
        max_tokens=config.max_tokens,
    )


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(
    request: AgentRunRequest,
    db: asyncpg.Connection = Depends(get_db),
) -> AgentRunResponse:
    start = time.time()

    try:
        task_type = await classify_task(request.message)

        logger.info(
            "agent_dispatch",
            agent=request.agent_name,
            client_id=request.client_id,
            task_type=task_type.value,
        )

        messages = list(request.context) + [{"role": "user", "content": request.message}]
        result = await call_model(messages, task_type)

        cost = compute_cost(result["model"], result["tokens_in"], result["tokens_out"])
        duration_ms = int((time.time() - start) * 1000)

        await log_task(
            conn=db,
            client_id=request.client_id,
            agent_name=request.agent_name,
            model=result["model"],
            tokens_in=result["tokens_in"],
            tokens_out=result["tokens_out"],
            cost_usd=cost,
            duration_ms=duration_ms,
        )

        logger.info(
            "agent_done",
            agent=request.agent_name,
            model=result["model"],
            tokens_in=result["tokens_in"],
            tokens_out=result["tokens_out"],
            cost_usd=cost,
            duration_ms=duration_ms,
        )

        return AgentRunResponse(
            response=result["content"],
            agent_name=request.agent_name,
            model_used=result["model"],
            tokens_in=result["tokens_in"],
            tokens_out=result["tokens_out"],
            cost_usd=cost,
            duration_ms=duration_ms,
        )

    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        logger.error("agent_run_failed", agent=request.agent_name, error=str(e), duration_ms=duration_ms)
        await alert_error(context=f"POST /agents/run agent={request.agent_name}", error=e)
        raise HTTPException(status_code=500, detail=str(e))
