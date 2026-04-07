import time

from fastapi import APIRouter

from api.core.logging import get_logger, log_task_event
from api.core.model_router import classify_task, get_model_config
from api.models.schemas import AgentRunRequest, AgentRunResponse

router = APIRouter()
logger = get_logger(__name__)


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(request: AgentRunRequest) -> AgentRunResponse:
    start = time.perf_counter()

    task_type = await classify_task(request.message)
    model_config = get_model_config(task_type)

    logger.info(
        "agent_dispatch",
        agent=request.agent_name,
        client_id=request.client_id,
        task_type=task_type,
        model=model_config.model,
    )

    # TODO: replace stub with real model client call
    # e.g. response_text, tokens_in, tokens_out = await call_model(model_config, request)
    response_text = f"Agent {request.agent_name} received: {request.message}"
    tokens_in = len(request.message.split())
    tokens_out = 10
    cost_usd = 0.0

    duration_ms = int((time.perf_counter() - start) * 1000)

    log_task_event(
        agent=request.agent_name,
        model=model_config.model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        client_id=request.client_id,
        duration_ms=duration_ms,
    )

    return AgentRunResponse(
        response=response_text,
        agent_name=request.agent_name,
        model_used=model_config.model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
    )
