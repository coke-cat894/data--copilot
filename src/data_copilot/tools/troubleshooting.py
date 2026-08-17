"""Minimal bounded Agent-facing Tools over Phase 4.1-4.3 diagnostics."""

from hashlib import sha256
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from data_copilot.diagnostics import (
    DiagnosticEvidence,
    DiagnosticEvidenceBuilder,
    DatasetSnapshot,
    PipelineEvidence,
    PipelineEvidenceBuilder,
    PostgresDiagnosticResult,
    TroubleshootingResources,
    compare_pipeline_runs,
    compare_snapshots,
)
from data_copilot.errors import (
    DiagnosticCollectionError,
    DiagnosticResourceError,
    ToolArgumentError,
    UnknownToolError,
)
from data_copilot.llm.models import ToolDefinition


TroubleshootingToolResult: TypeAlias = DiagnosticEvidence | PipelineEvidence


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CollectTableDiagnosticsArguments(_Arguments):
    schema_name: str = Field(description="Exact PostgreSQL schema name.")
    table_name: str = Field(description="Exact table or view name.")


class CompareTableSnapshotsArguments(_Arguments):
    before_snapshot_id: str = Field(
        description="Program-listed logical baseline snapshot ID."
    )
    after_snapshot_id: str = Field(
        description="Program-listed or previously collected logical snapshot ID."
    )


class InspectPipelineRunArguments(_Arguments):
    pipeline_id: str = Field(description="Program-listed logical pipeline ID.")
    run_id: str = Field(description="Program-listed logical run ID.")


class ComparePipelineRunsArguments(_Arguments):
    pipeline_id: str = Field(description="Program-listed logical pipeline ID.")
    before_run_id: str = Field(description="Program-listed baseline run ID.")
    after_run_id: str = Field(description="Program-listed incident run ID.")


_ALL_ARGUMENT_MODELS: dict[str, type[_Arguments]] = {
    "collect_table_diagnostics": CollectTableDiagnosticsArguments,
    "compare_table_snapshots": CompareTableSnapshotsArguments,
    "inspect_pipeline_run": InspectPipelineRunArguments,
    "compare_pipeline_runs": ComparePipelineRunsArguments,
}

_DESCRIPTIONS = {
    "collect_table_diagnostics": (
        "Collect one bounded read-only PostgreSQL table-health snapshot using "
        "program-owned queries; connection, SQL, and limits are not arguments."
    ),
    "compare_table_snapshots": (
        "Compare two available same-table snapshots for deterministic schema, row, "
        "null, distinct, duplicate, and range drift; never infers cause."
    ),
    "inspect_pipeline_run": (
        "Return bounded sanitized PIPELINE_EVIDENCE for one available run: status, "
        "steps, counts/timing, and selected warning/error events."
    ),
    "compare_pipeline_runs": (
        "Compare two available runs with bounded factual PIPELINE_EVIDENCE; never "
        "infers root cause."
    ),
}


class TroubleshootingToolSet:
    """Expose only Tools supported by explicitly supplied program resources."""

    def __init__(
        self,
        database_id: str,
        resources: TroubleshootingResources,
        *,
        diagnostic_evidence_builder: DiagnosticEvidenceBuilder | None = None,
        pipeline_evidence_builder: PipelineEvidenceBuilder | None = None,
    ) -> None:
        self._database_id = database_id
        self._resources = resources
        self._diagnostic_builder = (
            diagnostic_evidence_builder or DiagnosticEvidenceBuilder()
        )
        self._pipeline_builder = pipeline_evidence_builder or PipelineEvidenceBuilder()
        self._collected: dict[str, PostgresDiagnosticResult] = {}
        enabled: list[str] = []
        if resources.collector is not None:
            enabled.append("collect_table_diagnostics")
        if len(resources.snapshots) >= 2 or (
            resources.collector is not None and resources.snapshots
        ):
            enabled.append("compare_table_snapshots")
        if resources.pipeline_runs:
            enabled.append("inspect_pipeline_run")
        pipelines_with_comparisons = {
            run.pipeline_id
            for run in resources.pipeline_runs
            if sum(
                candidate.pipeline_id == run.pipeline_id
                for candidate in resources.pipeline_runs
            )
            >= 2
        }
        if pipelines_with_comparisons:
            enabled.append("compare_pipeline_runs")
        self._argument_models = {
            name: _ALL_ARGUMENT_MODELS[name] for name in enabled
        }
        self._schemas = tuple(
            ToolDefinition(
                name=name,
                description=_DESCRIPTIONS[name],
                parameters=_strict_json_schema(self._argument_models[name]),
            )
            for name in enabled
        )

    @property
    def schemas(self) -> tuple[ToolDefinition, ...]:
        return self._schemas

    @property
    def allowed_tool_names(self) -> frozenset[str]:
        return frozenset(self._argument_models)

    def dispatch(self, name: str, arguments: str) -> TroubleshootingToolResult:
        model = self._argument_models.get(name)
        if model is None:
            raise UnknownToolError("Unsupported tool.")
        try:
            parsed = model.model_validate_json(arguments, strict=True)
        except (ValidationError, ValueError, TypeError):
            raise ToolArgumentError("Tool arguments are invalid.") from None
        return self._invoke(name, parsed)

    def _invoke(
        self,
        name: str,
        arguments: _Arguments,
    ) -> TroubleshootingToolResult:
        if name == "collect_table_diagnostics" and isinstance(
            arguments, CollectTableDiagnosticsArguments
        ):
            result = self._collect(arguments.schema_name, arguments.table_name)
            return self._diagnostic_builder.build_snapshot(self._database_id, result)
        if name == "compare_table_snapshots" and isinstance(
            arguments, CompareTableSnapshotsArguments
        ):
            before = self._snapshot(arguments.before_snapshot_id)
            after = self._snapshot(arguments.after_snapshot_id)
            return self._diagnostic_builder.build_comparison(
                self._database_id,
                compare_snapshots(before, after),
            )
        if name == "inspect_pipeline_run" and isinstance(
            arguments, InspectPipelineRunArguments
        ):
            run = self._resources.get_pipeline_run(
                arguments.pipeline_id,
                arguments.run_id,
            )
            return self._pipeline_builder.build(run)
        if name == "compare_pipeline_runs" and isinstance(
            arguments, ComparePipelineRunsArguments
        ):
            before = self._resources.get_pipeline_run(
                arguments.pipeline_id,
                arguments.before_run_id,
            )
            after = self._resources.get_pipeline_run(
                arguments.pipeline_id,
                arguments.after_run_id,
            )
            return self._pipeline_builder.build(
                after,
                compare_pipeline_runs(before, after),
            )
        raise ToolArgumentError("Tool arguments do not match the requested Tool.")

    def _collect(self, schema_name: str, table_name: str) -> PostgresDiagnosticResult:
        dataset_id = f"{schema_name.strip()}.{table_name.strip()}"
        cached = self._collected.get(dataset_id)
        if cached is not None:
            return cached
        collector = self._resources.collector
        if collector is None:
            raise DiagnosticResourceError("Live diagnostic collection is unavailable.")
        result = collector.collect(
            self._database_id,
            schema_name=schema_name,
            table_name=table_name,
        )
        if result.snapshot.dataset_id != dataset_id:
            raise DiagnosticCollectionError(
                "Collected snapshot identity did not match the requested table."
            )
        snapshot = result.snapshot.model_copy(
            update={
                "snapshot_id": (
                    "collected:"
                    + sha256(dataset_id.encode("utf-8")).hexdigest()[:16]
                )
            }
        )
        cached = result.model_copy(update={"snapshot": snapshot})
        self._collected[dataset_id] = cached
        return cached

    def _snapshot(self, snapshot_id: str) -> DatasetSnapshot:
        for result in self._collected.values():
            if result.snapshot.snapshot_id == snapshot_id:
                return result.snapshot
        return self._resources.get_snapshot(snapshot_id)


def _strict_json_schema(model: type[_Arguments]) -> dict[str, Any]:
    schema = model.model_json_schema()

    def make_strict(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            node.pop("title", None)
            if node.get("type") == "object":
                properties = node.get("properties", {})
                if isinstance(properties, dict):
                    node["required"] = list(properties)
                node["additionalProperties"] = False
            for value in node.values():
                make_strict(value)
        elif isinstance(node, list):
            for value in node:
                make_strict(value)

    make_strict(schema)
    return schema
