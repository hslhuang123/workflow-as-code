from .anthropic import AnthropicAgentProvider
from .base import AgentProvider, AgentResult
from .fake import FakeAgentProvider

PROVIDER_NAMES = ("fake", "anthropic")


def create_provider(name: str = "fake", *, model: str | None = None) -> AgentProvider:
    if name == "fake":
        return FakeAgentProvider()
    if name == "anthropic":
        return AnthropicAgentProvider(model=model)
    allowed = ", ".join(PROVIDER_NAMES)
    raise ValueError(f"unknown provider {name!r}; allowed providers: {allowed}")


__all__ = [
    "AgentProvider",
    "AgentResult",
    "AnthropicAgentProvider",
    "FakeAgentProvider",
    "PROVIDER_NAMES",
    "create_provider",
]
