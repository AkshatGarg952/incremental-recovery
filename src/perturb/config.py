"""Load `config/providers.yaml` and build the real, cached, throttled
clients the perturbation CLI uses — the same provider/model split the rest
of the project reads from config, not hardcoded here.
"""

from pathlib import Path

import yaml

from src.llm.cache import CachingChatClient, ResponseCache
from src.llm.gemini import GeminiClient
from src.llm.groq import GroqClient
from src.llm.throttle import ThrottledChatClient

_DEFAULT_PROVIDERS_PATH = Path("config/providers.yaml")


def load_providers_config(path: str | Path = _DEFAULT_PROVIDERS_PATH) -> dict:
    with open(path) as handle:
        return yaml.safe_load(handle)


# Empirically, 2s (30 req/min) was not conservative enough for Gemini's
# free-tier rate limit and exhausted ThrottledChatClient's retries outright
# on a real batch run — free-tier RPM caps are typically stricter on Gemini
# than Groq, hence the different defaults. Override per-provider if your
# tier's limits differ.
_DEFAULT_CLASSIFY_MIN_INTERVAL_SECONDS = 5.0  # ~12 req/min
_DEFAULT_POLICY_MIN_INTERVAL_SECONDS = 2.5  # ~24 req/min
_MAX_RETRIES = 8
_BASE_BACKOFF_SECONDS = 2.0


def build_role_clients(
    cache: ResponseCache,
    providers_config: dict,
    prompt_version: str = "v1",
    classify_min_interval_seconds: float = _DEFAULT_CLASSIFY_MIN_INTERVAL_SECONDS,
    policy_min_interval_seconds: float = _DEFAULT_POLICY_MIN_INTERVAL_SECONDS,
) -> tuple[CachingChatClient, str, CachingChatClient, str]:
    """Returns `(classify_client, classify_model, policy_client, policy_model)`."""
    classify_role = providers_config["roles"]["classify"]
    policy_role = providers_config["roles"]["policy"]

    classify_client = CachingChatClient(
        ThrottledChatClient(
            GeminiClient(),
            min_interval_seconds=classify_min_interval_seconds,
            max_retries=_MAX_RETRIES,
            base_backoff_seconds=_BASE_BACKOFF_SECONDS,
        ),
        cache,
        role="classify",
        provider=classify_role["provider"],
        prompt_version=prompt_version,
    )
    policy_client = CachingChatClient(
        ThrottledChatClient(
            GroqClient(),
            min_interval_seconds=policy_min_interval_seconds,
            max_retries=_MAX_RETRIES,
            base_backoff_seconds=_BASE_BACKOFF_SECONDS,
        ),
        cache,
        role="policy",
        provider=policy_role["provider"],
        prompt_version=prompt_version,
    )
    return classify_client, classify_role["model"], policy_client, policy_role["model"]
