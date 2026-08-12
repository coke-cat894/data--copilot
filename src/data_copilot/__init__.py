"""Data Copilot public package surface with isolated lazy imports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data_copilot.agent import AgentResult, DataCopilotAgent
    from data_copilot.database_agent import DatabaseCopilotAgent

__all__ = ["AgentResult", "DataCopilotAgent", "DatabaseCopilotAgent"]


def __getattr__(name: str) -> object:
    """Preserve public Agent imports without coupling unrelated subpackages."""

    if name in {"AgentResult", "DataCopilotAgent"}:
        from data_copilot.agent import AgentResult, DataCopilotAgent

        value = {
            "AgentResult": AgentResult,
            "DataCopilotAgent": DataCopilotAgent,
        }[name]
    elif name == "DatabaseCopilotAgent":
        from data_copilot.database_agent import DatabaseCopilotAgent

        value = DatabaseCopilotAgent
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value
