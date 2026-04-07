from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ── Agent ─────────────────────────────────────────────────────────────────────

class AgentRunRequest(BaseModel):
    message: str
    agent_name: str = "orchestrator"
    client_id: str = "internal"
    context: list[dict] = Field(default_factory=list)


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    response: str
    agent_name: str
    model_used: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    duration_ms: int


# ── Telegram ──────────────────────────────────────────────────────────────────

class TelegramFrom(BaseModel):
    id: int
    username: str | None = None
    first_name: str | None = None
    is_bot: bool = False


class TelegramChat(BaseModel):
    id: int
    type: str = "private"


class TelegramMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_id: int
    text: str | None = None
    chat: TelegramChat
    from_: TelegramFrom | None = Field(None, alias="from")


class TelegramUpdate(BaseModel):
    update_id: int
    message: TelegramMessage | None = None


# ── Task log ──────────────────────────────────────────────────────────────────

class TaskLog(BaseModel):
    id: int | None = None
    client_id: str
    agent_name: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    duration_ms: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── Client ────────────────────────────────────────────────────────────────────

class ClientCreate(BaseModel):
    name: str
    plan: str
    daily_budget_usd: float


class ClientResponse(BaseModel):
    id: int
    name: str
    plan: str
    daily_budget_usd: float
    is_active: bool
    created_at: datetime
