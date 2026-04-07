PRICING: dict[str, dict] = {
    "claude-sonnet-4-6":     {"in": 3.00,  "out": 15.00, "provider": "anthropic"},
    "claude-haiku-4-5":      {"in": 0.80,  "out": 4.00,  "provider": "anthropic"},
    "gpt-4o":                {"in": 2.50,  "out": 10.00, "provider": "openai"},
    "gpt-4o-mini":           {"in": 0.15,  "out": 0.60,  "provider": "openai"},
    "qwen3-30b-a3b":         {"in": 1.20,  "out": 1.20,  "provider": "qwen"},
    "qwen3:8b":              {"in": 0.00,  "out": 0.00,  "provider": "ollama"},
    "qwen3:14b":             {"in": 0.00,  "out": 0.00,  "provider": "ollama"},
    "qwq-32b":               {"in": 0.00,  "out": 0.00,  "provider": "ollama"},
    "text-embedding-3-small": {"in": 0.02, "out": 0.00,  "provider": "openai"},
}


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Returns cost in USD. Returns 0.0 for unknown models — never raises."""
    pricing = PRICING.get(model)
    if not pricing:
        return 0.0
    cost = (tokens_in * pricing["in"] + tokens_out * pricing["out"]) / 1_000_000
    return round(cost, 6)


def get_provider(model: str) -> str:
    """Returns provider string. Returns 'unknown' if model not found."""
    pricing = PRICING.get(model)
    return pricing["provider"] if pricing else "unknown"


def format_cost(cost_usd: float) -> str:
    """Returns human-readable cost string."""
    if cost_usd < 0.01:
        return f"${cost_usd:.6f}"
    return f"${cost_usd:.2f}"
