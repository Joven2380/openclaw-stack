import time

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.core.agent_runner import get_agent_info, list_agents, run_agent
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


class AgentListItem(BaseModel):
    name: str
    role: str
    description: str
    model: str
    provider: str
    tools: list[str]
    escalation_to: str


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


@router.get("/list", response_model=list[AgentListItem])
async def agents_list() -> list[AgentListItem]:
    """Return metadata for all available agents defined in agents/*.yaml."""
    agents = []
    for slug in list_agents():
        try:
            info = get_agent_info(slug)
            agents.append(AgentListItem(**info))
        except Exception as exc:
            logger.warning("agent_list_skip", slug=slug, error=str(exc))
    return agents


@router.post("/run", response_model=AgentRunResponse)
async def run(
    request: AgentRunRequest,
    db: asyncpg.Connection = Depends(get_db),
) -> AgentRunResponse:
    """Run a named agent or fall back to task-type routing for unknown agents.

    If request.agent_name matches an agents/*.yaml file, the request is handled
    by agent_runner.run_agent (persona + memory + provider routing).
    Otherwise, the legacy classify → call_model path is used.
    """
    start = time.time()

    try:
        known = list_agents()

        if request.agent_name in known:
            # --- Persona-aware agent path ---
            result = await run_agent(
                agent_name=request.agent_name,
                user_message=request.message,
                client_id=request.client_id,
                context=list(request.context),
                conn=db,
            )
            logger.info(
                "agent_done",
                agent=request.agent_name,
                model=result["model"],
                tokens_in=result["tokens_in"],
                tokens_out=result["tokens_out"],
                cost_usd=result["cost_usd"],
                duration_ms=result["duration_ms"],
            )
            return AgentRunResponse(
                response=result["response"],
                agent_name=request.agent_name,
                model_used=result["model"],
                tokens_in=result["tokens_in"],
                tokens_out=result["tokens_out"],
                cost_usd=result["cost_usd"],
                duration_ms=result["duration_ms"],
            )

        # --- Legacy task-type routing path (e.g. agent_name="orchestrator") ---
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

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        logger.error("agent_run_failed", agent=request.agent_name, error=str(exc), duration_ms=duration_ms)
        await alert_error(context=f"POST /agents/run agent={request.agent_name}", error=exc)
        raise HTTPException(status_code=500, detail=str(exc))
