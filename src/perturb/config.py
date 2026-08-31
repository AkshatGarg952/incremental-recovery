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


def build_role_clients(
    cache: ResponseCache,
    providers_config: dict,
    prompt_version: str = "v1",
    min_interval_seconds: float = 2.0,
) -> tuple[CachingChatClient, str, CachingChatClient, str]:
    """Returns `(classify_client, classify_model, policy_client, policy_model)`."""
    classify_role = providers_config["roles"]["classify"]
    policy_role = providers_config["roles"]["policy"]

    classify_client = CachingChatClient(
        ThrottledChatClient(GeminiClient(), min_interval_seconds=min_interval_seconds),
        cache,
        role="classify",
        provider=classify_role["provider"],
        prompt_version=prompt_version,
    )
    policy_client = CachingChatClient(
        ThrottledChatClient(GroqClient(), min_interval_seconds=min_interval_seconds),
        cache,
        role="policy",
        provider=policy_role["provider"],
        prompt_version=prompt_version,
    )
    return classify_client, classify_role["model"], policy_client, policy_role["model"]
