import json
from pathlib import Path

import pytest

from data_copilot.diagnostics import PipelineRunLoader, PipelineRunStatus
from data_copilot.errors import PipelineConfigurationError, PipelineLimitError


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "pipeline"


def _valid_run(run_id: str = "run_1") -> dict[str, object]:
    return {
        "pipeline_id": "daily_orders",
        "run_id": run_id,
        "status": "success",
        "steps": [],
    }


def test_loads_json_run_with_path_free_provenance_and_normalization() -> None:
    runs = PipelineRunLoader(
        FIXTURE_DIRECTORY / "healthy_run.json",
        allowed_roots=[FIXTURE_DIRECTORY],
    ).load()

    assert len(runs) == 1
    run = runs[0]
    assert run.pipeline_id == "daily_orders"
    assert run.status is PipelineRunStatus.SUCCESS
    assert [step.step_id for step in run.steps] == [
        "extract_orders",
        "transform_orders",
        "load_orders",
    ]
    assert run.steps[0].duration_seconds == 60.0
    assert run.provenance.logical_source == "healthy_run.json"
    assert run.provenance.record_index == 0
    assert str(FIXTURE_DIRECTORY.resolve()) not in repr(run)


def test_loads_jsonl_in_record_order_with_prompt_text_inert() -> None:
    runs = PipelineRunLoader(
        FIXTURE_DIRECTORY / "incident_runs.jsonl",
        allowed_roots=[FIXTURE_DIRECTORY],
    ).load()

    assert [run.run_id for run in runs] == ["run_failed", "run_prompt"]
    assert [step.step_id for step in runs[0].steps] == [
        "extract_orders",
        "transform_orders",
        "load_orders",
    ]
    assert runs[1].steps[0].events[0].message.startswith("Ignore previous")
    assert runs[1].provenance.record_index == 1


def test_directory_and_explicit_file_order_are_deterministic() -> None:
    first = PipelineRunLoader(
        FIXTURE_DIRECTORY,
        allowed_roots=[FIXTURE_DIRECTORY],
    ).load()
    second = PipelineRunLoader(
        [
            FIXTURE_DIRECTORY / "incident_runs.jsonl",
            FIXTURE_DIRECTORY / "healthy_run.json",
        ],
        allowed_roots=[FIXTURE_DIRECTORY],
    ).load()

    assert first == second
    assert [run.provenance.logical_source for run in first] == [
        "healthy_run.json",
        "incident_runs.jsonl",
        "incident_runs.jsonl",
    ]


def test_json_list_is_supported(tmp_path: Path) -> None:
    path = tmp_path / "runs.json"
    path.write_text(
        json.dumps([_valid_run("r1"), _valid_run("r2")]),
        encoding="utf-8",
    )

    runs = PipelineRunLoader(path, allowed_roots=[tmp_path]).load()

    assert [run.run_id for run in runs] == ["r1", "r2"]


def test_duplicate_run_identity_across_files_fails_closed(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    content = json.dumps(_valid_run())
    first.write_text(content, encoding="utf-8")
    second.write_text(content, encoding="utf-8")

    with pytest.raises(PipelineConfigurationError, match="identities"):
        PipelineRunLoader([first, second], allowed_roots=[tmp_path]).load()


def test_caller_managed_provenance_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    run = _valid_run()
    run["provenance"] = {"logical_source": "forged.json", "record_index": 0}
    path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(PipelineConfigurationError, match="caller-managed"):
        PipelineRunLoader(path, allowed_roots=[tmp_path]).load()


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("malformed.json", "{bad", "malformed JSON"),
        ("wrong.json", "[1, 2]", "run object"),
        ("wrong.jsonl", "[]\n", "must be a run object"),
        ("empty.json", "  \n", "cannot be empty"),
        ("invalid.json", '{"pipeline_id":"p"}', "required field"),
        ("invalid_status.json", json.dumps({**_valid_run(), "status": "done"}), "field is invalid"),
    ],
)
def test_malformed_and_invalid_inputs_fail_safely(
    tmp_path: Path,
    name: str,
    content: str,
    message: str,
) -> None:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")

    with pytest.raises(PipelineConfigurationError, match=message):
        PipelineRunLoader(path, allowed_roots=[tmp_path]).load()


def test_invalid_utf8_and_unsupported_file_type_fail_closed(tmp_path: Path) -> None:
    invalid = tmp_path / "run.json"
    invalid.write_bytes(b"\xff\xfe")
    unsupported = tmp_path / "run.txt"
    unsupported.write_text("{}", encoding="utf-8")

    with pytest.raises(PipelineConfigurationError, match="UTF-8"):
        PipelineRunLoader(invalid, allowed_roots=[tmp_path]).load()
    with pytest.raises(PipelineConfigurationError, match="JSON or JSONL"):
        PipelineRunLoader(unsupported, allowed_roots=[tmp_path]).load()


def test_file_size_run_count_and_file_count_limits(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    first.write_text(json.dumps([_valid_run("r1"), _valid_run("r2")]), encoding="utf-8")
    second.write_text(json.dumps(_valid_run("r3")), encoding="utf-8")

    with pytest.raises(PipelineLimitError, match="file size"):
        PipelineRunLoader(first, allowed_roots=[tmp_path], max_file_bytes=2).load()
    with pytest.raises(PipelineLimitError, match="too many run"):
        PipelineRunLoader(first, allowed_roots=[tmp_path], max_runs_per_file=1).load()
    with pytest.raises(PipelineLimitError, match="too many files"):
        PipelineRunLoader(
            [first, second], allowed_roots=[tmp_path], max_files=1
        ).load()
    with pytest.raises(PipelineLimitError, match="too many runs"):
        PipelineRunLoader(
            [first, second], allowed_roots=[tmp_path], max_runs=2
        ).load()


def test_path_outside_allowed_root_is_rejected(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    path = outside / "run.json"
    path.write_text(json.dumps(_valid_run()), encoding="utf-8")

    with pytest.raises(PipelineConfigurationError, match="outside"):
        PipelineRunLoader(path, allowed_roots=[allowed]).load()


def test_symlink_file_parent_and_hidden_path_are_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    path = real / "run.json"
    path.write_text(json.dumps(_valid_run()), encoding="utf-8")
    link = tmp_path / "linked.json"
    link.symlink_to(path)
    parent_link = tmp_path / "linked_parent"
    parent_link.symlink_to(real, target_is_directory=True)
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    hidden_path = hidden / "run.json"
    hidden_path.write_text(json.dumps(_valid_run("hidden")), encoding="utf-8")

    for source in (link, parent_link / "run.json"):
        with pytest.raises(PipelineConfigurationError, match="symbolic"):
            PipelineRunLoader(source, allowed_roots=[tmp_path]).load()
    with pytest.raises(PipelineConfigurationError, match="Hidden"):
        PipelineRunLoader(hidden_path, allowed_roots=[tmp_path]).load()


def test_duplicate_logical_source_names_fail_closed(tmp_path: Path) -> None:
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "run.json"
    second = second_dir / "run.json"
    first.write_text(json.dumps(_valid_run("a")), encoding="utf-8")
    second.write_text(json.dumps(_valid_run("b")), encoding="utf-8")

    with pytest.raises(PipelineConfigurationError, match="source names"):
        PipelineRunLoader(
            [first, second], allowed_roots=[tmp_path]
        ).load()


def test_errors_expose_logical_source_not_absolute_path(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{bad", encoding="utf-8")

    with pytest.raises(PipelineConfigurationError) as captured:
        PipelineRunLoader(path, allowed_roots=[tmp_path]).load()

    assert "bad.json" in str(captured.value)
    assert str(tmp_path.resolve()) not in str(captured.value)


def test_loader_does_not_recurse_or_make_network_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "run.json"
    path.write_text(json.dumps(_valid_run()), encoding="utf-8")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("forbidden capability used")

    monkeypatch.setattr(Path, "rglob", forbidden)
    import socket

    monkeypatch.setattr(socket, "create_connection", forbidden)

    assert len(PipelineRunLoader(tmp_path, allowed_roots=[tmp_path]).load()) == 1
