"""JSONL loaders for eval cases and deterministic mock scripts."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from data_copilot.errors import DataCopilotError
from data_copilot.evals.models import EvalCase
from data_copilot.llm import LLMResponse


class EvalLoadError(DataCopilotError):
    """Raised when an eval input is malformed or ambiguous."""


class MockScript(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    responses: tuple[LLMResponse, ...]


def load_cases(path: Path) -> tuple[EvalCase, ...]:
    cases = _load_jsonl(path, EvalCase)
    _require_unique_ids(cases, path)
    return tuple(cases)


def load_mock_scripts(path: Path) -> dict[str, tuple[LLMResponse, ...]]:
    scripts = _load_jsonl(path, MockScript)
    _require_unique_ids(scripts, path)
    return {script.case_id: script.responses for script in scripts}


def _load_jsonl(path: Path, model: type[BaseModel]) -> list[BaseModel]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EvalLoadError("Eval input could not be read.") from exc
    loaded: list[BaseModel] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            loaded.append(model.model_validate_json(line))
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            raise EvalLoadError(
                f"Eval input is invalid at line {line_number}."
            ) from exc
    if not loaded:
        raise EvalLoadError("Eval input contains no cases.")
    return loaded


def _require_unique_ids(items: list[BaseModel], path: Path) -> None:
    ids = [str(getattr(item, "case_id")) for item in items]
    if len(ids) != len(set(ids)):
        raise EvalLoadError(f"Eval input contains duplicate case IDs: {path.name}.")
