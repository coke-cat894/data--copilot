import importlib

from data_copilot import AgentResult, DataCopilotAgent, DatabaseCopilotAgent
from data_copilot.cli import build_doctor_parser, build_parser


def test_supported_root_public_exports_are_importable() -> None:
    assert AgentResult.__module__ == "data_copilot.agent"
    assert DataCopilotAgent.__module__ == "data_copilot.agent"
    assert DatabaseCopilotAgent.__module__ == "data_copilot.database_agent"


def test_primary_package_boundaries_import_without_cycles() -> None:
    modules = (
        "data_copilot.agent",
        "data_copilot.database_agent",
        "data_copilot.llm",
        "data_copilot.datasets",
        "data_copilot.execution",
        "data_copilot.sql",
        "data_copilot.tools",
        "data_copilot.semantics",
        "data_copilot.documents",
        "data_copilot.diagnostics",
        "data_copilot.evals",
        "data_copilot.cli",
        "data_copilot.doctor",
    )

    assert all(importlib.import_module(module) is not None for module in modules)


def test_cli_help_identifies_interactive_doctor_and_eval_entry_points() -> None:
    interactive_help = build_parser().format_help()
    doctor_help = build_doctor_parser().format_help()

    assert "data-copilot doctor" in interactive_help
    assert "data-copilot-eval" in interactive_help
    assert "without contacting an LLM provider" in doctor_help
    assert "--connect-database" in doctor_help
    assert "--json" in doctor_help
