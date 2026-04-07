import logging

import structlog
from structlog.types import FilteringBoundLogger


def configure_logging(log_level: str, app_env: str = "development") -> None:
    log_level_num = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if app_env == "production":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level_num),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> FilteringBoundLogger:
    return structlog.get_logger(name)


def log_task_event(
    agent: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    client_id: str = "internal",
    duration_ms: int = 0,
) -> None:
    logger = get_logger("task_event")
    logger.info(
        "task_complete",
        agent=agent,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=round(cost_usd, 6),
        client_id=client_id,
        duration_ms=duration_ms,
    )
