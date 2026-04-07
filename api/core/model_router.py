from dataclasses import dataclass
from enum import Enum

from api.core.config import get_settings
from api.core.logging import get_logger

logger = get_logger(__name__)


class TaskType(str, Enum):
    SIMPLE = "SIMPLE"
    TOOL_CALL = "TOOL_CALL"
    REASONING = "REASONING"
    CODE = "CODE"
    VISION = "VISION"
    ORCHESTRATE = "ORCHESTRATE"


@dataclass
class ModelConfig:
    model: str
    provider: str
    max_tokens: int
    timeout_seconds: int
    fallback_model: str


ROUTING_TABLE: dict[TaskType, ModelConfig] = {
    TaskType.SIMPLE: ModelConfig(
        model="qwen3:8b",
        provider="ollama",
        max_tokens=1000,
        timeout_seconds=30,
        fallback_model="qwen3-30b-a3b",
    ),
    TaskType.TOOL_CALL: ModelConfig(
        model="qwen3-30b-a3b",
        provider="qwen",
        max_tokens=8000,
        timeout_seconds=60,
        fallback_model="gpt-4o",
    ),
    TaskType.REASONING: ModelConfig(
        model="qwq-32b",
        provider="ollama",
        max_tokens=16000,
        timeout_seconds=120,
        fallback_model="claude-sonnet-4-6",
    ),
    TaskType.CODE: ModelConfig(
        model="gpt-4o",
        provider="openai",
        max_tokens=8000,
        timeout_seconds=60,
        fallback_model="claude-sonnet-4-6",
    ),
    TaskType.VISION: ModelConfig(
        model="claude-sonnet-4-6",
        provider="anthropic",
        max_tokens=4000,
        timeout_seconds=60,
        fallback_model="gpt-4o",
    ),
    TaskType.ORCHESTRATE: ModelConfig(
        model="claude-sonnet-4-6",
        provider="anthropic",
        max_tokens=4000,
        timeout_seconds=60,
        fallback_model="gpt-4o",
    ),
}


def _keyword_classify(message: str) -> TaskType:
    lower = message.lower()
    if any(kw in lower for kw in ("code", "debug", "function", "script", "error")):
        return TaskType.CODE
    if any(kw in lower for kw in ("image", "screenshot", "photo", "document")):
        return TaskType.VISION
    if any(kw in lower for kw in ("think", "reason", "analyze", "complex")):
        return TaskType.REASONING
    if any(kw in lower for kw in ("search", "lookup", "fetch", "tool")):
        return TaskType.TOOL_CALL
    return TaskType.ORCHESTRATE


async def classify_task(message: str) -> TaskType:
    settings = get_settings()

    if not settings.GEMINI_API_KEY:
        return _keyword_classify(message)

    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = (
            "Classify the following message into exactly one of these categories: "
            "SIMPLE, TOOL_CALL, REASONING, CODE, VISION, ORCHESTRATE.\n"
            "Reply with only the category name, nothing else.\n\n"
            f"Message: {message}"
        )
        response = await model.generate_content_async(prompt)
        category = response.text.strip().upper()
        return TaskType[category]
    except KeyError:
        logger.warning("gemini_classify_unknown_category", message=message[:100])
        return _keyword_classify(message)
    except Exception as e:
        logger.warning("gemini_classify_failed", error=str(e))
        return _keyword_classify(message)


def get_model_config(task_type: TaskType) -> ModelConfig:
    return ROUTING_TABLE[task_type]
