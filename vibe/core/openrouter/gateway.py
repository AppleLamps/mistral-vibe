from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from vibe.core.config import ModelConfig

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


@dataclass
class OpenRouterModelCache:
    models: list[dict[str, Any]]
    stored_at_timestamp: float


def _get_cache_path() -> Path:
    """Get the cache file path for OpenRouter models."""
    from vibe.core.paths.global_paths import VIBE_HOME

    cache_dir = VIBE_HOME.path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "openrouter_models.json"


def _is_cache_fresh(cache: OpenRouterModelCache) -> bool:
    """Check if the cache is still within TTL."""
    return cache.stored_at_timestamp > time.time() - CACHE_TTL_SECONDS


def _load_cache() -> OpenRouterModelCache | None:
    """Load models from cache file if it exists and is valid."""
    cache_path = _get_cache_path()
    if not cache_path.exists():
        return None

    try:
        data = json.loads(cache_path.read_text())
        return OpenRouterModelCache(
            models=data.get("models", []),
            stored_at_timestamp=data.get("stored_at_timestamp", 0),
        )
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load OpenRouter cache: {e}")
        return None


def _save_cache(cache: OpenRouterModelCache) -> None:
    """Save models to cache file."""
    cache_path = _get_cache_path()
    try:
        cache_path.write_text(json.dumps(asdict(cache), indent=2))
    except OSError as e:
        logger.warning(f"Failed to save OpenRouter cache: {e}")


def _generate_alias(model_id: str) -> str:
    """Generate a user-friendly alias from OpenRouter model ID.

    Examples:
        anthropic/claude-sonnet-4-20250514 -> or:claude-sonnet-4
        openai/gpt-4o -> or:gpt-4o
        meta-llama/llama-3.3-70b-instruct -> or:llama-3.3-70b
    """
    # Remove provider prefix
    if "/" in model_id:
        model_name = model_id.split("/", 1)[1]
    else:
        model_name = model_id

    # Remove date suffixes like -20250514
    model_name = re.sub(r"-\d{8}$", "", model_name)

    # Remove common suffixes for brevity
    model_name = re.sub(r"-instruct$", "", model_name)
    model_name = re.sub(r"-chat$", "", model_name)

    return f"or:{model_name}"


def _supports_tools(model_data: dict[str, Any]) -> bool:
    """Check if a model supports tool/function calling."""
    supported_params = model_data.get("supported_parameters", [])
    if not supported_params:
        # If no supported_parameters, check architecture
        arch = model_data.get("architecture", {})
        return arch.get("instruct_type") is not None

    return "tools" in supported_params or "functions" in supported_params


def _parse_model(model_data: dict[str, Any]) -> dict[str, Any] | None:
    """Parse OpenRouter model data into ModelConfig-compatible dict."""
    model_id = model_data.get("id", "")
    if not model_id:
        return None

    # Filter out models that don't support tools
    if not _supports_tools(model_data):
        return None

    pricing = model_data.get("pricing", {})
    # OpenRouter prices are per token, we need per million tokens
    try:
        input_price = float(pricing.get("prompt", 0)) * 1_000_000
        output_price = float(pricing.get("completion", 0)) * 1_000_000
    except (TypeError, ValueError):
        input_price = 0.0
        output_price = 0.0

    return {
        "name": model_id,
        "provider": "openrouter",
        "alias": _generate_alias(model_id),
        "input_price": input_price,
        "output_price": output_price,
    }


class OpenRouterGateway:
    """Gateway for fetching available models from OpenRouter API."""

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout

    async def fetch_models(self, api_key: str | None = None) -> list[ModelConfig]:
        """Fetch available models from OpenRouter, using cache when fresh.

        Args:
            api_key: Optional API key. If not provided, will try OPENROUTER_API_KEY env var.

        Returns:
            List of ModelConfig objects for tool-capable models.
        """
        from vibe.core.config import ModelConfig

        # Check cache first
        cache = _load_cache()
        if cache and _is_cache_fresh(cache):
            logger.debug("Using cached OpenRouter models")
            return self._models_from_cache(cache.models)

        # Fetch from API
        api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            logger.debug("No OpenRouter API key available, skipping model fetch")
            # Return cached models even if stale, or empty list
            if cache:
                return self._models_from_cache(cache.models)
            return []

        try:
            models_data = await self._fetch_from_api(api_key)
            # Save to cache
            _save_cache(
                OpenRouterModelCache(
                    models=models_data,
                    stored_at_timestamp=time.time(),
                )
            )
            return self._models_from_cache(models_data)
        except Exception as e:
            logger.warning(f"Failed to fetch OpenRouter models: {e}")
            # Fall back to stale cache if available
            if cache:
                logger.debug("Falling back to stale cache")
                return self._models_from_cache(cache.models)
            return []

    async def _fetch_from_api(self, api_key: str) -> list[dict[str, Any]]:
        """Fetch models from OpenRouter API."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/mistralai/mistral-vibe",
            "X-Title": "Mistral Vibe",
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(OPENROUTER_MODELS_URL, headers=headers)
            response.raise_for_status()
            data = response.json()

        return data.get("data", [])

    def _models_from_cache(self, models_data: list[dict[str, Any]]) -> list[ModelConfig]:
        """Convert cached model data to ModelConfig objects."""
        from vibe.core.config import ModelConfig

        models = []
        seen_aliases: set[str] = set()

        for model_data in models_data:
            parsed = _parse_model(model_data)
            if parsed:
                alias = parsed["alias"]
                # Handle duplicate aliases by appending provider prefix
                if alias in seen_aliases:
                    # Use full model id as alias instead
                    alias = f"or:{parsed['name'].replace('/', '-')}"
                    parsed["alias"] = alias

                if alias not in seen_aliases:
                    seen_aliases.add(alias)
                    models.append(ModelConfig(**parsed))

        return models
