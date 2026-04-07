import httpx
import anthropic
import openai

from api.core.config import get_settings
from api.core.logging import get_logger
from api.core.model_router import ModelConfig, ROUTING_TABLE, TaskType

logger = get_logger(__name__)

# Provider lookup used when building fallback ModelConfig
_PROVIDER_MAP: dict[str, str] = {
    "claude-sonnet-4-6": "anthropic",
    "claude-haiku-4-5": "anthropic",
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "qwen3-30b-a3b": "qwen",
    "qwen3:8b": "ollama",
    "qwen3:14b": "ollama",
    "qwq-32b": "ollama",
}


async def call_anthropic(
    messages: list[dict],
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 4000,
    system: str | None = None,
    temperature: float | None = None,
) -> dict:
    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("Anthropic not configured: ANTHROPIC_API_KEY is empty")

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        kwargs: dict = {}
        if system:
            kwargs["system"] = system
        if temperature is not None:
            kwargs["temperature"] = temperature

        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages,
            **kwargs,
        )
        return {
            "content": response.content[0].text,
            "tokens_in": response.usage.input_tokens,
            "tokens_out": response.usage.output_tokens,
            "model": response.model,
        }
    except anthropic.APIError as e:
        raise RuntimeError(f"Anthropic API error ({e.status_code}): {e.message}") from e
    except Exception as e:
        raise RuntimeError(f"Anthropic call failed: {e}") from e


async def call_openai(
    messages: list[dict],
    model: str = "gpt-4o",
    max_tokens: int = 8000,
    system: str | None = None,
    temperature: float | None = None,
) -> dict:
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OpenAI not configured: OPENAI_API_KEY is empty")

    try:
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        kwargs: dict = {}
        if temperature is not None:
            kwargs["temperature"] = temperature

        client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=all_messages,
            **kwargs,
        )
        return {
            "content": response.choices[0].message.content or "",
            "tokens_in": response.usage.prompt_tokens,
            "tokens_out": response.usage.completion_tokens,
            "model": response.model,
        }
    except openai.APIError as e:
        raise RuntimeError(f"OpenAI API error ({e.status_code}): {e.message}") from e
    except Exception as e:
        raise RuntimeError(f"OpenAI call failed: {e}") from e


async def call_qwen(
    messages: list[dict],
    model: str = "qwen3-30b-a3b",
    max_tokens: int = 8000,
    system: str | None = None,
    temperature: float | None = None,
) -> dict:
    settings = get_settings()
    if not settings.QWEN_API_KEY:
        raise RuntimeError("Qwen not configured: QWEN_API_KEY is empty")

    try:
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        kwargs: dict = {}
        if temperature is not None:
            kwargs["temperature"] = temperature

        client = openai.AsyncOpenAI(
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_BASE_URL,
        )
        response = await client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=all_messages,
            **kwargs,
        )
        return {
            "content": response.choices[0].message.content or "",
            "tokens_in": response.usage.prompt_tokens,
            "tokens_out": response.usage.completion_tokens,
            "model": response.model,
        }
    except openai.APIError as e:
        raise RuntimeError(f"Qwen API error ({e.status_code}): {e.message}") from e
    except Exception as e:
        raise RuntimeError(f"Qwen call failed: {e}") from e


async def call_ollama(
    messages: list[dict],
    model: str = "qwen3:8b",
    max_tokens: int = 1000,
    system: str | None = None,
    temperature: float | None = None,
) -> dict:
    settings = get_settings()

    try:
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        options: dict = {"num_predict": max_tokens}
        if temperature is not None:
            options["temperature"] = temperature

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            response = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": model,
                    "messages": all_messages,
                    "stream": False,
                    "options": options,
                },
            )
            response.raise_for_status()
            data = response.json()

        content = data["message"]["content"]
        # Ollama doesn't return token counts reliably — estimate from chars
        tokens_in = len(str(all_messages)) // 4
        tokens_out = len(content) // 4
        return {
            "content": content,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "model": model,
        }
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Ollama HTTP error ({e.response.status_code}): {e.response.text[:200]}") from e
    except httpx.ConnectError:
        raise RuntimeError(f"Ollama not reachable at {get_settings().OLLAMA_BASE_URL}") from None
    except Exception as e:
        raise RuntimeError(f"Ollama call failed: {e}") from e


def _build_fallback_config(model_name: str) -> ModelConfig:
    """Find a ModelConfig for a fallback model name. Checks ROUTING_TABLE first."""
    for cfg in ROUTING_TABLE.values():
        if cfg.model == model_name:
            return cfg
    # Not a primary model — construct a sensible default
    provider = _PROVIDER_MAP.get(model_name, "anthropic")
    return ModelConfig(
        model=model_name,
        provider=provider,
        max_tokens=4000,
        timeout_seconds=60,
        fallback_model="",  # no triple-fallback
    )


async def _call_provider(
    config: ModelConfig,
    messages: list[dict],
    system: str | None,
    temperature: float | None = None,
) -> dict:
    if config.provider == "anthropic":
        return await call_anthropic(messages, config.model, config.max_tokens, system, temperature)
    if config.provider == "openai":
        return await call_openai(messages, config.model, config.max_tokens, system, temperature)
    if config.provider == "qwen":
        return await call_qwen(messages, config.model, config.max_tokens, system, temperature)
    if config.provider == "ollama":
        return await call_ollama(messages, config.model, config.max_tokens, system, temperature)
    raise RuntimeError(f"Unknown provider: {config.provider}")


async def call_model(
    messages: list[dict],
    task_type: TaskType,
    system: str | None = None,
    override_model: str | None = None,
    temperature: float | None = None,
) -> dict:
    """Master dispatch. Routes to the correct provider, retries fallback once on failure."""
    config = ROUTING_TABLE[task_type]

    if override_model:
        config = ModelConfig(
            model=override_model,
            provider=_PROVIDER_MAP.get(override_model, config.provider),
            max_tokens=config.max_tokens,
            timeout_seconds=config.timeout_seconds,
            fallback_model=config.fallback_model,
        )

    try:
        result = await _call_provider(config, messages, system, temperature)
        result["provider"] = config.provider
        result["task_type"] = task_type.value
        return result

    except Exception as primary_err:
        logger.warning(
            "model_primary_failed",
            model=config.model,
            provider=config.provider,
            error=str(primary_err),
        )

        if not config.fallback_model:
            raise

        fallback_config = _build_fallback_config(config.fallback_model)
        logger.info("model_trying_fallback", fallback=fallback_config.model, provider=fallback_config.provider)

        try:
            result = await _call_provider(fallback_config, messages, system, temperature)
            result["provider"] = fallback_config.provider
            result["task_type"] = task_type.value
            return result
        except Exception as fallback_err:
            logger.error(
                "model_fallback_failed",
                primary=config.model,
                fallback=fallback_config.model,
                error=str(fallback_err),
            )
            raise RuntimeError(
                f"Both {config.model} and fallback {fallback_config.model} failed. "
                f"Primary: {primary_err}. Fallback: {fallback_err}"
            ) from fallback_err
