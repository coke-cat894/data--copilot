import json
from pathlib import Path

from data_copilot.cli import run_cli, run_doctor_cli
from data_copilot.databases import PostgresConnectionConfig
from data_copilot.doctor import DoctorReport, HealthStatus, inspect_environment


POSTGRES_ENV = {
    "DATA_COPILOT_POSTGRES_DSN": (
        "postgresql://analyst:test-password@db.example:5432/analytics"
    )
}


def _statuses(report: DoctorReport) -> dict[str, HealthStatus]:
    return {check.name: check.status for check in report.checks}


def test_default_doctor_is_provider_free_and_optional_capabilities_do_not_fail(
    tmp_path: Path,
) -> None:
    report = inspect_environment(environ={}, artifact_directory=tmp_path)
    statuses = _statuses(report)

    assert report.exit_code == 0
    assert statuses["package_runtime"] is HealthStatus.PASS
    assert statuses["runtime_configuration"] is HealthStatus.PASS
    assert statuses["provider_configuration"] is HealthStatus.WARN
    assert statuses["provider_connectivity"] is HealthStatus.SKIPPED
    assert statuses["postgres_configuration"] is HealthStatus.SKIPPED
    assert statuses["postgres_connectivity"] is HealthStatus.SKIPPED


def test_invalid_runtime_configuration_fails_without_exposing_values() -> None:
    secret_value = "sensitive-retry-value"

    report = inspect_environment(
        environ={"DATA_COPILOT_PROVIDER_MAX_RETRIES": secret_value},
        artifact_directory=None,
    )
    runtime = next(
        check for check in report.checks if check.name == "runtime_configuration"
    )

    assert report.exit_code == 1
    assert runtime.status is HealthStatus.FAIL
    assert secret_value not in runtime.summary


def test_database_connectivity_requires_explicit_opt_in() -> None:
    calls: list[PostgresConnectionConfig] = []

    report = inspect_environment(
        environ=POSTGRES_ENV,
        database_connectivity_check=calls.append,
        artifact_directory=None,
    )

    assert calls == []
    assert _statuses(report)["postgres_configuration"] is HealthStatus.PASS
    assert _statuses(report)["postgres_connectivity"] is HealthStatus.SKIPPED


def test_explicit_database_connectivity_uses_injected_read_only_check() -> None:
    calls: list[PostgresConnectionConfig] = []

    report = inspect_environment(
        environ=POSTGRES_ENV,
        connect_database=True,
        database_connectivity_check=calls.append,
        artifact_directory=None,
    )

    assert len(calls) == 1
    assert report.exit_code == 0
    assert _statuses(report)["postgres_connectivity"] is HealthStatus.PASS


def test_connectivity_failure_is_sanitized() -> None:
    secret = "driver-secret-detail"

    def fail(_config: PostgresConnectionConfig) -> None:
        raise RuntimeError(secret)

    report = inspect_environment(
        environ=POSTGRES_ENV,
        connect_database=True,
        database_connectivity_check=fail,
        artifact_directory=None,
    )
    connectivity = next(
        check for check in report.checks if check.name == "postgres_connectivity"
    )

    assert connectivity.status is HealthStatus.FAIL
    assert "RuntimeError" in connectivity.summary
    assert secret not in connectivity.summary


def test_explicit_semantic_document_and_root_checks_load_local_sources(
    tmp_path: Path,
) -> None:
    fixture_root = Path(__file__).parent / "fixtures"

    report = inspect_environment(
        environ={},
        semantic_source=fixture_root / "semantic",
        document_source=fixture_root / "business_documents",
        allowed_roots=(tmp_path,),
        artifact_directory=tmp_path,
    )
    statuses = _statuses(report)

    assert report.exit_code == 0
    assert statuses["semantic_source"] is HealthStatus.PASS
    assert statuses["document_source"] is HealthStatus.PASS
    assert statuses["allowed_roots"] is HealthStatus.PASS
    assert statuses["artifact_directory"] is HealthStatus.PASS


def test_invalid_explicit_semantic_source_has_actionable_safe_failure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "missing"

    report = inspect_environment(
        environ={},
        semantic_source=source,
        artifact_directory=None,
    )
    semantic = next(
        check for check in report.checks if check.name == "semantic_source"
    )

    assert semantic.status is HealthStatus.FAIL
    assert semantic.summary == "Semantic path does not exist."
    assert str(source) not in semantic.summary


def test_doctor_json_cli_is_machine_readable_and_dispatchable(tmp_path: Path) -> None:
    outputs: list[str] = []

    exit_code = run_doctor_cli(
        ["--json", "--artifact-directory", str(tmp_path)],
        output_fn=outputs.append,
    )
    payload = json.loads(outputs[0])

    assert exit_code in {0, 1}
    assert payload["schema_version"] == "1.0"
    assert any(check["name"] == "provider_connectivity" for check in payload["checks"])

    dispatched: list[str] = []
    dispatch_code = run_cli(
        ["doctor", "--json", "--artifact-directory", str(tmp_path)],
        output_fn=dispatched.append,
    )
    assert dispatch_code in {0, 1}
    assert json.loads(dispatched[0])["schema_version"] == "1.0"
