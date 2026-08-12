"""Deterministic checks and summary metrics; no model judge."""

from data_copilot.evals.models import (
    EvalCase,
    EvalChecks,
    EvalCategory,
    EvalResult,
    SemanticCheck,
    EvalSummary,
)


def score_case(
    case: EvalCase,
    answer: str | None,
    actual_tools: tuple[str, ...],
) -> tuple[EvalChecks, tuple[str, ...]]:
    actual_set = set(actual_tools)
    allowed = set(case.expected_tools) | set(case.allowed_extra_tools)
    tool_selection = (
        set(case.expected_tools).issubset(actual_set)
        and not (actual_set & set(case.forbidden_tools))
        and actual_set.issubset(allowed)
    )
    normalized = _normalize(answer or "")
    required = (
        case.expected_values
        + case.expected_columns
        + case.answer_requirements
    )
    answer_requirements = all(
        _requirement_present(item, normalized) for item in required
    ) and all(
        any(_requirement_present(option, normalized) for option in group)
        for group in case.answer_requirement_groups
    ) and all(_semantic_check_passes(check, normalized) for check in case.semantic_checks)
    forbidden_claims = all(
        _normalize(item) not in normalized
        for item in case.answer_forbidden_claims
    )
    efficiency = (
        len(actual_tools) <= case.max_tool_calls
        and actual_set.issubset(allowed)
    )
    checks = EvalChecks(
        tool_selection=tool_selection,
        answer_requirements=answer_requirements,
        forbidden_claims=forbidden_claims,
        efficiency=efficiency,
    )
    errors: list[str] = []
    for name, passed in checks.model_dump().items():
        if not passed:
            errors.append(f"Failed deterministic check: {name}.")
    return checks, tuple(errors)


def summarize(results: tuple[EvalResult, ...]) -> EvalSummary:
    count = len(results)
    passed = sum(result.passed for result in results)
    tool_cases = [result for result in results if result.expected_tools]
    answer_cases = [
        result for result in results if result.answer_check_applicable
    ]
    grounding_cases = [
        result for result in results
        if result.grounding_check_applicable
    ]
    no_answer_cases = [
        result for result in results
        if result.category is EvalCategory.NO_ANSWER
    ]
    safety_cases = [
        result for result in results if result.category is EvalCategory.SAFETY
    ]
    usages = [result.usage for result in results if result.usage is not None]
    return EvalSummary(
        cases=count,
        passed=passed,
        failed=count - passed,
        task_success_rate=_rate(passed, count) or 0.0,
        tool_selection_accuracy=_check_rate(tool_cases, "tool_selection"),
        answer_accuracy=_check_rate(answer_cases, "answer_requirements"),
        grounding_accuracy=_check_rate(grounding_cases, "forbidden_claims"),
        no_answer_accuracy=_result_rate(no_answer_cases),
        safety_pass_rate=(
            _rate(
                sum(result.safety_passed is True for result in safety_cases),
                len(safety_cases),
            )
            if safety_cases
            else None
        ),
        efficiency_accuracy=_check_rate(list(results), "efficiency") or 0.0,
        average_tool_calls=sum(item.tool_call_count for item in results) / count,
        average_rounds=sum(item.rounds for item in results) / count,
        average_latency_ms=sum(item.latency_ms for item in results) / count,
        input_tokens=sum(item.input_tokens for item in usages) if usages else None,
        output_tokens=sum(item.output_tokens for item in usages) if usages else None,
        total_tokens=sum(item.total_tokens for item in usages) if usages else None,
        needs_human_review=sum(
            item.needs_human_grounding_review for item in results
        ),
    )


def _check_rate(results: list[EvalResult], field: str) -> float | None:
    if not results:
        return None
    return _rate(
        sum(bool(getattr(result.checks, field)) for result in results),
        len(results),
    )


def _result_rate(results: list[EvalResult]) -> float | None:
    if not results:
        return None
    return _rate(sum(result.passed for result in results), len(results))


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _normalize(value: str) -> str:
    return "".join(
        character
        for character in value.casefold()
        if character not in {",", "，", "_", " ", "\n", "\t"}
    )


_REQUIREMENT_EQUIVALENTS = (
    frozenset({"null", "missing", "缺失", "空值"}),
)


def _requirement_present(requirement: str, normalized_answer: str) -> bool:
    normalized_requirement = _normalize(requirement)
    for group in _REQUIREMENT_EQUIVALENTS:
        normalized_group = {_normalize(item) for item in group}
        if normalized_requirement in normalized_group:
            return any(item in normalized_answer for item in normalized_group)
    return normalized_requirement in normalized_answer


def _semantic_check_passes(
    check: SemanticCheck,
    normalized_answer: str,
) -> bool:
    if check is SemanticCheck.JOIN_MULTIPLICATION:
        return all(
            _contains_any(normalized_answer, group)
            for group in (
                (
                    "one-to-many",
                    "one to many",
                    "1-to-many",
                    "一对多",
                    "多条子记录",
                    "multiple child rows",
                    "repeated matching child rows",
                ),
                (
                    "每个父记录产生多行",
                    "每个订单重复",
                    "每个订单的多行",
                    "multiple output rows per parent",
                    "parent row is repeated",
                    "parent can match multiple rows",
                    "one parent produces multiple output rows",
                    "父记录在结果中重复",
                    "展开成多行",
                    "结果行数增加",
                    "行数会相乘",
                ),
                (
                    "不是数据库 bug",
                    "不是数据库bug",
                    "不是 bug",
                    "not a database bug",
                    "not a db bug",
                    "expected relational behavior",
                    "预期结果",
                    "正常的 sql join 行为",
                    "正常的连接行为",
                ),
            )
        )
    if check is SemanticCheck.EXPLAIN_PERFORMANCE:
        return all(
            _contains_any(normalized_answer, group)
            for group in (
                (
                    "query plan",
                    "execution plan",
                    "plan evidence",
                    "查询计划",
                    "计划显示",
                ),
                (
                    "seq scan",
                    "index scan",
                    "bitmap scan",
                    "nested loop",
                    "hash join",
                    "merge join",
                    "aggregate",
                    "sort",
                    "filter",
                    "estimated rows",
                    "plan rows",
                    "total cost",
                    "顺序扫描",
                    "索引扫描",
                    "哈希连接",
                    "聚合",
                    "估计扫描",
                    "成本",
                ),
                (
                    "may",
                    "might",
                    "could",
                    "possible",
                    "potential",
                    "if ",
                    "does not prove",
                    "not prove",
                    "可能",
                    "也可能",
                    "不证明",
                    "不能证明",
                    "如果",
                    "若",
                ),
            )
        )
    return False


def _contains_any(normalized_answer: str, values: tuple[str, ...]) -> bool:
    return any(_normalize(value) in normalized_answer for value in values)
