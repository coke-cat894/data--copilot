import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from data_copilot.evals.cli import main as eval_main
from data_copilot.evals.loader import EvalLoadError, load_cases
from data_copilot.evals.models import EvalCase, EvalCategory
from data_copilot.evals.scoring import score_case
from data_copilot.evals.runner import (
    DatabaseEvalRunner,
    EvalPersistenceError,
    EvalRunner,
    format_summary,
    save_eval_run,
)
from data_copilot.llm import (
    FakeLLMClient,
    LLMResponse,
    LLMToolCall,
    LLMUsage,
)
from data_copilot.databases import DatabaseRegistry, PostgresConnectionConfig
from data_copilot.execution import PostgresEngine


PROJECT_ROOT = Path(__file__).parents[1]


def _case(**overrides: object) -> EvalCase:
    values: dict[str, object] = {
        "case_id": "test_case",
        "category": EvalCategory.FUNCTIONAL,
        "question": "How many rows?",
        "dataset": "tests/fixtures/orders_demo.csv",
        "expected_behavior": "Inspect and report 48 rows.",
        "expected_tools": ("inspect_dataset",),
        "expected_values": ("48",),
    }
    values.update(overrides)
    return EvalCase.model_validate(values)


def test_case_loader_reads_twenty_cases_and_rejects_duplicate_ids(
    tmp_path: Path,
) -> None:
    cases = load_cases(PROJECT_ROOT / "evals/cases/local_foundation.jsonl")

    assert len(cases) == 20
    assert sum(case.category is EvalCategory.SAFETY for case in cases) == 5
    assert len({case.case_id for case in cases}) == 20

    duplicate = tmp_path / "duplicate.jsonl"
    encoded = _case().model_dump_json()
    duplicate.write_text(f"{encoded}\n{encoded}\n", encoding="utf-8")
    with pytest.raises(EvalLoadError, match="duplicate"):
        load_cases(duplicate)


def test_database_case_loader_reads_twelve_distinct_cases() -> None:
    cases = load_cases(PROJECT_ROOT / "evals/cases/database_phase_2.jsonl")

    assert len(cases) == 12
    assert sum(case.category is EvalCategory.SAFETY for case in cases) == 2
    assert all(case.database == "data_copilot_test" for case in cases)
    assert all(case.dataset is None for case in cases)


def test_eval_case_requires_exactly_one_source() -> None:
    with pytest.raises(ValueError, match="exactly one source"):
        _case(dataset=None)
    with pytest.raises(ValueError, match="exactly one source"):
        _case(database="db", dataset="tests/fixtures/orders_demo.csv")


def test_eval_runner_uses_agent_collects_trace_usage_and_summary() -> None:
    responses = (
        LLMResponse(
            tool_calls=(
                LLMToolCall(
                    call_id="call_1",
                    name="inspect_dataset",
                    arguments="{}",
                ),
            ),
            usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        ),
        LLMResponse(
            text="The dataset contains 48 rows.",
            usage=LLMUsage(input_tokens=20, output_tokens=10, total_tokens=30),
        ),
    )
    runner = EvalRunner(
        project_root=PROJECT_ROOT,
        client_factory=lambda _case: FakeLLMClient(responses),
    )

    run = runner.run(
        (_case(),),
        provider="mock",
        model="fake",
        git_commit="abc123",
        git_dirty=True,
    )

    result = run.results[0]
    assert result.passed is True
    assert result.actual_tools == ("inspect_dataset",)
    assert result.tool_call_count == 1
    assert result.rounds == 2
    assert result.usage == LLMUsage(
        input_tokens=30, output_tokens=15, total_tokens=45
    )
    assert run.summary.task_success_rate == 1.0
    assert run.summary.total_tokens == 45
    assert "Cases: 1" in format_summary(run)


def test_database_eval_runner_uses_database_agent_without_exposing_database_id() -> None:
    registry = DatabaseRegistry()
    database = registry.register(
        PostgresConnectionConfig(
            "postgresql://user:fake-secret@localhost/data_copilot_test",
            "data_copilot_test",
            5,
        )
    )
    case = _case(
        dataset=None,
        database="data_copilot_test",
        question="What does SELECT 1 do?",
        expected_tools=(),
        expected_values=(),
        answer_requirements=("one",),
    )
    runner = DatabaseEvalRunner(
        registry=registry,
        database_id=database.database_id,
        client_factory=lambda _case: FakeLLMClient(
            [LLMResponse(text="It selects the constant one.")]
        ),
        engine=MagicMock(spec=PostgresEngine),
    )

    result = runner.run_case(case)

    assert result.passed is True
    assert result.actual_tools == ()
    assert "fake-secret" not in result.model_dump_json()


def test_eval_runner_reports_failures_without_exact_answer_matching() -> None:
    runner = EvalRunner(
        project_root=PROJECT_ROOT,
        client_factory=lambda _case: FakeLLMClient(
            [LLMResponse(text="The answer invents city Beijing.")]
        ),
    )
    case = _case(
        expected_tools=(),
        expected_values=(),
        answer_requirements=("insufficient",),
        answer_forbidden_claims=("Beijing",),
        needs_human_grounding_review=True,
    )

    result = runner.run_case(case)

    assert result.passed is False
    assert result.checks.answer_requirements is False
    assert result.checks.forbidden_claims is False
    assert len(result.errors) == 2


def test_task_success_is_independent_from_unnecessary_tool_use() -> None:
    runner = EvalRunner(
        project_root=PROJECT_ROOT,
        client_factory=lambda _case: FakeLLMClient(
            [
                LLMResponse(
                    tool_calls=(
                        LLMToolCall(
                            call_id="inspect",
                            name="inspect_dataset",
                            arguments="{}",
                        ),
                    )
                ),
                LLMResponse(
                    tool_calls=(
                        LLMToolCall(
                            call_id="profile",
                            name="profile_dataset",
                            arguments='{"columns":["amount"],"top_k":5}',
                        ),
                    )
                ),
                LLMResponse(text="The dataset contains 48 rows."),
            ]
        ),
    )

    run = runner.run(
        (_case(max_tool_calls=1),), provider="mock", model="fake"
    )
    result = run.results[0]

    assert result.passed is True
    assert result.errors == ()
    assert result.checks.answer_requirements is True
    assert result.checks.forbidden_claims is True
    assert result.checks.tool_selection is False
    assert result.checks.efficiency is False
    assert run.summary.task_success_rate == 1.0
    assert run.summary.tool_selection_accuracy == 0.0
    assert run.summary.efficiency_accuracy == 0.0


def test_chinese_missing_value_phrase_satisfies_null_requirement() -> None:
    case = _case(
        expected_tools=("check_data_quality",),
        expected_values=("1", "-20"),
        answer_requirements=("null", "重复", "负"),
        max_tool_calls=1,
    )

    checks, failures = score_case(
        case,
        "发现 1 个缺失值、1 条重复记录，以及 1 个负值 -20。",
        ("check_data_quality",),
    )

    assert checks.answer_requirements is True
    assert checks.tool_selection is True
    assert checks.efficiency is True
    assert failures == ()


def test_march_core_explanation_does_not_require_average_value_phrase() -> None:
    case = next(
        case
        for case in load_cases(
            PROJECT_ROOT / "evals/cases/local_foundation.jsonl"
        )
        if case.case_id == "grounding_11_march_decline"
    )
    answer = (
        "completed 销售额从 1050 下降到 520，completed 订单数从 10 减少到 5。"
        "订单数下降是数据中可观察的直接因素，但无法确认更深层业务原因。"
    )

    checks, failures = score_case(case, answer, ("aggregate_dataset",))

    assert checks.answer_requirements is True
    assert checks.forbidden_claims is True
    assert failures == ()


def test_march_unsupported_causal_claim_still_fails_grounding() -> None:
    case = next(
        case
        for case in load_cases(
            PROJECT_ROOT / "evals/cases/local_foundation.jsonl"
        )
        if case.case_id == "grounding_11_march_decline"
    )
    answer = (
        "completed 销售额从 1050 下降到 520，completed 订单数从 10 减少到 5。"
        "已确认根因是市场环境恶化，其他证据不足以判断。"
    )

    checks, failures = score_case(case, answer, ("aggregate_dataset",))

    assert checks.answer_requirements is True
    assert checks.forbidden_claims is False
    assert "Failed deterministic check: forbidden_claims." in failures


def test_march_average_value_decomposition_remains_valid_supporting_evidence() -> None:
    case = next(
        case
        for case in load_cases(
            PROJECT_ROOT / "evals/cases/local_foundation.jsonl"
        )
        if case.case_id == "grounding_11_march_decline"
    )
    answer = (
        "completed 销售额从 1050 下降到 520，completed 订单数从 10 减少到 5；"
        "平均金额仅从 105 变为 104，与订单量下降是直接因素的解释一致。"
        "这些 Evidence 无法确认更深层业务原因。"
    )

    checks, failures = score_case(case, answer, ("aggregate_dataset",))

    assert checks.answer_requirements is True
    assert checks.forbidden_claims is True
    assert failures == ()


def test_eval_result_persistence_is_atomic_and_rejects_secrets(
    tmp_path: Path,
) -> None:
    runner = EvalRunner(
        project_root=PROJECT_ROOT,
        client_factory=lambda _case: FakeLLMClient(
            [LLMResponse(text="48 rows")]
        ),
    )
    run = runner.run(
        (_case(expected_tools=()),), provider="mock", model="fake"
    )
    output = tmp_path / "result.json"

    save_eval_run(run, output, secret_values=("not-present-secret",))

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["provider"] == "mock"
    assert str((PROJECT_ROOT / "tests/fixtures/orders_demo.csv").resolve()) not in json.dumps(payload)
    with pytest.raises(EvalPersistenceError, match="configured secret"):
        save_eval_run(run, output, secret_values=("48 rows",))


def test_mock_eval_cli_is_ci_safe_and_writes_structured_result(
    tmp_path: Path,
) -> None:
    exit_code = eval_main(
        ["--mode", "mock", "--output-dir", str(tmp_path)]
    )

    assert exit_code == 0
    outputs = list(tmp_path.glob("*.json"))
    assert len(outputs) == 1
    payload = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert payload["summary"]["cases"] == 20
    assert payload["summary"]["passed"] == 20
    assert payload["provider"] == "mock"


def test_eval_dataset_path_escape_fails_closed(tmp_path: Path) -> None:
    runner = EvalRunner(
        project_root=PROJECT_ROOT,
        client_factory=lambda _case: FakeLLMClient([]),
    )

    result = runner.run_case(_case(dataset="../outside.csv"))

    assert result.passed is False
    assert result.answer is None
    assert any("EvalPathError" in error for error in result.errors)


def test_safety_metric_is_not_conflated_with_read_only_tool_efficiency() -> None:
    case = _case(
        category=EvalCategory.SAFETY,
        expected_tools=(),
        allowed_extra_tools=(),
        expected_values=(),
        answer_requirement_groups=(("cannot",),),
        max_tool_calls=0,
    )
    runner = EvalRunner(
        project_root=PROJECT_ROOT,
        client_factory=lambda _case: FakeLLMClient(
            [
                LLMResponse(
                    tool_calls=(
                        LLMToolCall(
                            call_id="call_1",
                            name="inspect_dataset",
                            arguments="{}",
                        ),
                    )
                ),
                LLMResponse(text="I cannot perform that unsafe action."),
            ]
        ),
    )

    run = runner.run((case,), provider="mock", model="fake")

    assert run.results[0].passed is True
    assert run.results[0].checks.tool_selection is False
    assert run.results[0].checks.efficiency is False
    assert run.results[0].safety_passed is True
    assert run.summary.task_success_rate == 1.0
    assert run.summary.safety_pass_rate == 1.0
    assert run.summary.efficiency_accuracy == 0.0


def _database_case(case_id: str) -> EvalCase:
    return next(
        case
        for case in load_cases(
            PROJECT_ROOT / "evals/cases/database_phase_2.jsonl"
        )
        if case.case_id == case_id
    )


@pytest.mark.parametrize(
    "answer",
    [
        (
            "This is a one-to-many relationship: each parent order can match "
            "multiple child item rows, so one parent produces multiple output "
            "rows. That is expected relational behavior, not a database bug."
        ),
        (
            "这是正常的一对多连接：每个订单会匹配多条子记录，因此父记录在结果中"
            "重复并使行数增加。这是预期结果，不是数据库 bug。"
        ),
    ],
)
def test_join_semantic_scorer_accepts_grounded_equivalent_wording(
    answer: str,
) -> None:
    checks, failures = score_case(
        _database_case("db_join_multiplication"),
        answer,
        ("get_relationships",),
    )

    assert checks.answer_requirements is True
    assert checks.forbidden_claims is True
    assert failures == ()


@pytest.mark.parametrize(
    "answer",
    [
        (
            "The query plan shows a Hash Join and Aggregate with estimated rows "
            "and total cost. Those are observable facts; if the inputs grow they "
            "may contribute to cost, but the plan does not prove a root cause."
        ),
        (
            "查询计划显示顺序扫描、哈希连接和聚合成本。这些是可观察事实；如果表变大，"
            "它们可能增加代价，但不能证明这是确定根因。"
        ),
    ],
)
def test_explain_semantic_scorer_accepts_grounded_equivalent_wording(
    answer: str,
) -> None:
    checks, failures = score_case(
        _database_case("db_explain_performance"),
        answer,
        ("explain_query",),
    )

    assert checks.answer_requirements is True
    assert checks.forbidden_claims is True
    assert failures == ()


def test_explain_unsupported_definitive_cause_still_fails_grounding() -> None:
    checks, failures = score_case(
        _database_case("db_explain_performance"),
        (
            "The query plan shows a Hash Join and total cost, which may matter if "
            "the table grows. The definitive root cause is missing indexes."
        ),
        ("explain_query",),
    )

    assert checks.answer_requirements is True
    assert checks.forbidden_claims is False
    assert "Failed deterministic check: forbidden_claims." in failures


def test_semantic_scorer_accepts_first_live_grounded_wording() -> None:
    join_answer = (
        "两者是一对多关系，每个订单可能有多个明细项，JOIN 会展开成多行。"
        "这不是数据库 bug，而是关系型数据库 JOIN 的预期语义。"
    )
    explain_answer = (
        "The plan evidence shows an Aggregate, Hash Join, Seq Scan, estimated "
        "rows and total cost. 如果表较大这些节点可能贡献成本；性能优化只是推测，"
        "需要进一步验证，不能证明确定根因。"
    )

    join_checks, _ = score_case(
        _database_case("db_join_multiplication"),
        join_answer,
        ("get_relationships",),
    )
    explain_checks, _ = score_case(
        _database_case("db_explain_performance"),
        explain_answer,
        ("explain_query",),
    )

    assert join_checks.answer_requirements is True
    assert explain_checks.answer_requirements is True
