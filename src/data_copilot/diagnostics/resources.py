"""Program-approved bounded resources for optional troubleshooting Tools."""

from collections import Counter
from collections.abc import Sequence
import json
from typing import Any

from data_copilot.diagnostics.models import DatasetSnapshot
from data_copilot.diagnostics.pipeline_evidence_builder import sanitize_pipeline_text
from data_copilot.diagnostics.pipeline_models import PipelineRun
from data_copilot.diagnostics.postgres import PostgresDiagnosticCollector
from data_copilot.errors import (
    DiagnosticComparisonUnavailableError,
    DiagnosticResourceError,
)


MAX_TROUBLESHOOTING_SNAPSHOTS = 100
MAX_TROUBLESHOOTING_RUNS = 500
MAX_TROUBLESHOOTING_RESOURCE_METADATA_CHARS = 16_000


class TroubleshootingResources:
    """Hold typed resources; discovery remains separate from Tool permission."""

    def __init__(
        self,
        *,
        collector: PostgresDiagnosticCollector | None = None,
        snapshots: Sequence[DatasetSnapshot] = (),
        pipeline_runs: Sequence[PipelineRun] = (),
    ) -> None:
        if isinstance(snapshots, (str, bytes)) or not isinstance(snapshots, Sequence):
            raise TypeError("snapshots must be a sequence.")
        if isinstance(pipeline_runs, (str, bytes)) or not isinstance(
            pipeline_runs, Sequence
        ):
            raise TypeError("pipeline_runs must be a sequence.")
        if any(not isinstance(value, DatasetSnapshot) for value in snapshots):
            raise TypeError("snapshots must contain DatasetSnapshot models.")
        if any(not isinstance(value, PipelineRun) for value in pipeline_runs):
            raise TypeError("pipeline_runs must contain PipelineRun models.")
        if len(snapshots) > MAX_TROUBLESHOOTING_SNAPSHOTS:
            raise DiagnosticResourceError("Too many diagnostic snapshots configured.")
        if len(pipeline_runs) > MAX_TROUBLESHOOTING_RUNS:
            raise DiagnosticResourceError("Too many pipeline runs configured.")
        if any(snapshot.snapshot_id is None for snapshot in snapshots):
            raise DiagnosticResourceError(
                "Configured diagnostic snapshots require logical snapshot IDs."
            )
        for snapshot in snapshots:
            _validate_public_identity(snapshot.snapshot_id, "Snapshot ID")
            _validate_public_identity(snapshot.dataset_id, "Dataset ID")
        for run in pipeline_runs:
            _validate_public_identity(run.pipeline_id, "Pipeline ID")
            _validate_public_identity(run.run_id, "Run ID")
        snapshot_ids = [snapshot.snapshot_id for snapshot in snapshots]
        if len(snapshot_ids) != len(set(snapshot_ids)):
            raise DiagnosticResourceError("Diagnostic snapshot IDs must be unique.")
        run_ids = [(run.pipeline_id, run.run_id) for run in pipeline_runs]
        if len(run_ids) != len(set(run_ids)):
            raise DiagnosticResourceError("Pipeline run identities must be unique.")
        self._collector = collector
        self._snapshots = tuple(snapshots)
        self._pipeline_runs = tuple(pipeline_runs)
        self._snapshot_by_id = {
            snapshot.snapshot_id: snapshot for snapshot in self._snapshots
        }
        self._run_by_id = {
            (run.pipeline_id, run.run_id): run for run in self._pipeline_runs
        }
        if len(
            json.dumps(
                self.to_public_metadata(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        ) > MAX_TROUBLESHOOTING_RESOURCE_METADATA_CHARS:
            raise DiagnosticResourceError(
                "Troubleshooting resource metadata exceeds its context bound."
            )

    @property
    def collector(self) -> PostgresDiagnosticCollector | None:
        return self._collector

    @property
    def snapshots(self) -> tuple[DatasetSnapshot, ...]:
        return self._snapshots

    @property
    def pipeline_runs(self) -> tuple[PipelineRun, ...]:
        return self._pipeline_runs

    @property
    def has_capabilities(self) -> bool:
        return bool(self._collector or self._snapshots or self._pipeline_runs)

    def get_snapshot(self, snapshot_id: str) -> DatasetSnapshot:
        snapshot = self._snapshot_by_id.get(snapshot_id)
        if snapshot is None:
            raise DiagnosticComparisonUnavailableError(
                "Required diagnostic comparison input is unavailable."
            )
        return snapshot

    def get_pipeline_run(self, pipeline_id: str, run_id: str) -> PipelineRun:
        run = self._run_by_id.get((pipeline_id, run_id))
        if run is None:
            raise DiagnosticResourceError("Pipeline run is unavailable.")
        return run

    def to_public_metadata(self) -> dict[str, Any]:
        snapshot_counts = Counter(
            snapshot.dataset_id for snapshot in self._snapshots
        )
        return {
            "live_table_diagnostics": self._collector is not None,
            "snapshots": [
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "dataset_id": snapshot.dataset_id,
                    "captured_at": (
                        snapshot.captured_at.isoformat()
                        if snapshot.captured_at is not None
                        else None
                    ),
                }
                for snapshot in self._snapshots
            ],
            "snapshot_comparison_state": [
                {
                    "dataset_id": dataset_id,
                    "snapshot_count": snapshot_count,
                    "comparison_available": snapshot_count >= 2,
                    "unavailable_reason": (
                        None
                        if snapshot_count >= 2
                        else "baseline_or_before_snapshot_unavailable"
                    ),
                }
                for dataset_id, snapshot_count in sorted(snapshot_counts.items())
            ],
            "pipeline_runs": [
                {
                    "pipeline_id": run.pipeline_id,
                    "run_id": run.run_id,
                    "execution_time": (
                        run.execution_time.isoformat()
                        if run.execution_time is not None
                        else None
                    ),
                    "status": run.status.value,
                }
                for run in self._pipeline_runs
            ],
        }


def _validate_public_identity(value: str | None, label: str) -> None:
    if value is None or "/" in value or "\\" in value:
        raise DiagnosticResourceError(f"{label} must be a path-free logical identity.")
    if sanitize_pipeline_text(value) != value:
        raise DiagnosticResourceError(f"{label} cannot contain secret-like content.")
