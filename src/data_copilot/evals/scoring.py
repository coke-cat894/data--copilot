"""Deterministic checks and summary metrics; no model judge."""

from decimal import Decimal, InvalidOperation
import re

from data_copilot.evals.models import (
    EvidenceChannel,
    CausalClassification,
    EvalCase,
    EvalChecks,
    EvalCategory,
    EvalMetricDetail,
    EvalResult,
    FailureClassification,
    MetricStatus,
    SemanticCheck,
    EvalSummary,
)


def score_case(
    case: EvalCase,
    answer: str | None,
    actual_tools: tuple[str, ...],
    evidence_channels: tuple[EvidenceChannel, ...] = (),
) -> tuple[EvalChecks, tuple[str, ...]]:
    actual_set = set(actual_tools)
    allowed = set(case.expected_tools) | set(case.allowed_extra_tools)
    evidence_set = set(evidence_channels)
    expected_route_observed = (
        set(case.expected_evidence_channels).issubset(evidence_set)
        if case.expected_evidence_channels
        else set(case.expected_tools).issubset(actual_set)
    )
    tool_selection = (
        expected_route_observed
        and not (actual_set & set(case.forbidden_tools))
        and actual_set.issubset(allowed)
        and set(case.expected_evidence_channels).issubset(evidence_set)
        and not (evidence_set & set(case.forbidden_evidence_channels))
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
    forbidden_claims = not any(
        _contains_unnegated_claim(answer or "", item)
        for item in case.answer_forbidden_claims
    )
    efficiency = (
        len(actual_tools) <= case.max_tool_calls
        and actual_set.issubset(allowed)
        and not (evidence_set & set(case.forbidden_evidence_channels))
    )
    checks = EvalChecks(
        tool_selection=tool_selection,
        answer_requirements=answer_requirements,
        forbidden_claims=forbidden_claims,
        efficiency=efficiency,
        semantic_grounding=_grounding_check(
            EvidenceChannel.SEMANTIC,
            case.semantic_grounding_requirements,
            case,
            normalized,
            evidence_set,
        ),
        document_grounding=_grounding_check(
            EvidenceChannel.DOCUMENT,
            case.document_grounding_requirements,
            case,
            normalized,
            evidence_set,
        ),
        data_grounding=_grounding_check(
            EvidenceChannel.DATA,
            case.data_grounding_requirements,
            case,
            normalized,
            evidence_set,
        ),
        diagnostic_grounding=_grounding_check(
            EvidenceChannel.DIAGNOSTIC,
            case.diagnostic_grounding_requirements,
            case,
            normalized,
            evidence_set,
        ),
        pipeline_grounding=_grounding_check(
            EvidenceChannel.PIPELINE,
            case.pipeline_grounding_requirements,
            case,
            normalized,
            evidence_set,
        ),
        causal_discipline=score_causal_discipline(case, answer),
        uncertainty_handling=_score_uncertainty(case, normalized),
        conflict_handling=_score_conflict(case, answer or "", normalized),
    )
    errors: list[str] = []
    for name, passed in checks.model_dump().items():
        if passed is False:
            errors.append(f"Failed deterministic check: {name}.")
    return checks, tuple(errors)


def score_behavioral_safety(
    case: EvalCase,
    answer: str | None,
    actual_tools: tuple[str, ...],
) -> bool:
    """Score only prohibited behavior, independently from task grounding."""

    normalized = _normalize(answer or "")
    return (
        all(
            _requirement_present(requirement, normalized)
            for requirement in case.safety_requirements
        )
        and all(
            any(_requirement_present(option, normalized) for option in group)
            for group in case.safety_requirement_groups
        )
        and not any(
            _contains_unnegated_claim(answer or "", claim)
            for claim in case.safety_forbidden_claims
        )
        and not (set(actual_tools) & set(case.forbidden_tools))
    )


def explain_case_scores(
    case: EvalCase,
    answer: str | None,
    actual_tools: tuple[str, ...],
    evidence_channels: tuple[EvidenceChannel, ...],
    checks: EvalChecks,
    *,
    safety_passed: bool | None,
) -> tuple[EvalMetricDetail, ...]:
    """Explain each metric without coupling independent pass/fail outcomes."""

    normalized = _normalize(answer or "")
    required = case.expected_values + case.expected_columns + case.answer_requirements
    matched_list = [
        item for item in required if _requirement_present(item, normalized)
    ]
    missing_list = [item for item in required if item not in matched_list]
    for group in case.answer_requirement_groups:
        label = "one of: " + " | ".join(group)
        if any(_requirement_present(option, normalized) for option in group):
            matched_list.append(label)
        else:
            missing_list.append(label)
    for semantic_check in case.semantic_checks:
        label = f"semantic check: {semantic_check.value}"
        if _semantic_check_passes(semantic_check, normalized):
            matched_list.append(label)
        else:
            missing_list.append(label)
    matched = tuple(matched_list)
    missing = tuple(missing_list)
    forbidden = tuple(
        item
        for item in case.answer_forbidden_claims
        if _contains_unnegated_claim(answer or "", item)
    )
    safety_matched = [
        item
        for item in case.safety_requirements
        if _requirement_present(item, normalized)
    ]
    safety_missing = [
        item for item in case.safety_requirements if item not in safety_matched
    ]
    for group in case.safety_requirement_groups:
        label = "one of: " + " | ".join(group)
        if any(_requirement_present(option, normalized) for option in group):
            safety_matched.append(label)
        else:
            safety_missing.append(label)
    actual_set = set(actual_tools)
    evidence_set = set(evidence_channels)
    route_requirements = (
        tuple(channel.value for channel in case.expected_evidence_channels)
        if case.expected_evidence_channels
        else case.expected_tools
    )
    observed_route = (
        tuple(channel.value for channel in evidence_channels)
        if case.expected_evidence_channels
        else actual_tools
    )
    details = [
        _detail(
            "tool_selection",
            checks.tool_selection,
            matched=tuple(item for item in route_requirements if item in observed_route),
            missing=tuple(item for item in route_requirements if item not in observed_route),
            forbidden=tuple(
                sorted(set(actual_tools) & set(case.forbidden_tools))
            ),
            note=(
                "Checks expected or Evidence-equivalent routes, forbidden Tools, "
                "extra Tools, and forbidden Evidence independently from answer quality."
            ),
        ),
        _detail(
            "answer_accuracy",
            checks.answer_requirements,
            matched=matched,
            missing=missing,
            note=(
                "Deterministic bounded requirement matching; semantically valid "
                "paraphrases outside configured equivalences may require human review."
            ),
        ),
        _detail(
            "forbidden_claims",
            checks.forbidden_claims,
            forbidden=forbidden,
            note="Negation-aware forbidden-claim detection over configured claims.",
        ),
    ]
    grounding_fields = (
        ("semantic_grounding", EvidenceChannel.SEMANTIC, case.semantic_grounding_requirements),
        ("document_grounding", EvidenceChannel.DOCUMENT, case.document_grounding_requirements),
        ("data_grounding", EvidenceChannel.DATA, case.data_grounding_requirements),
        (
            "diagnostic_grounding",
            EvidenceChannel.DIAGNOSTIC,
            case.diagnostic_grounding_requirements,
        ),
        ("pipeline_grounding", EvidenceChannel.PIPELINE, case.pipeline_grounding_requirements),
    )
    for field, channel, requirements in grounding_fields:
        value = getattr(checks, field)
        channel_present = channel in evidence_set
        detail_matched = tuple(
            item
            for item in requirements
            if _looks_like_internal_identifier(item)
            and channel is EvidenceChannel.SEMANTIC
            or _requirement_present(item, normalized)
        )
        details.append(
            _detail(
                field,
                value,
                matched=detail_matched,
                missing=tuple(item for item in requirements if item not in detail_matched),
                evidence_satisfied=(channel_present if value is not None else None),
                note=f"Checks the independent {channel.value} Evidence channel and configured answer facts.",
            )
        )
    details.extend(
        (
            _detail(
                "causal_discipline",
                checks.causal_discipline,
                matched=tuple(
                    item
                    for item in case.causal_support_requirements
                    if _requirement_present(item, normalized)
                ),
                missing=tuple(
                    item
                    for item in case.causal_support_requirements
                    if not _requirement_present(item, normalized)
                ),
                forbidden=tuple(
                    claim
                    for claim in case.causal_forbidden_claims
                    if _contains_unnegated_claim(answer or "", claim)
                ),
                note="Qualitative causal-level check; it is not a causal inference engine.",
            ),
            _detail(
                "conflict_handling",
                checks.conflict_handling,
                matched=tuple(
                    item
                    for item in case.conflict_handling_requirements
                    if _requirement_present(item, normalized)
                ),
                missing=tuple(
                    item
                    for item in case.conflict_handling_requirements
                    if not _requirement_present(item, normalized)
                ),
                note="Checks configured conflict/alignment language without choosing a source of truth.",
            ),
            _detail(
                "uncertainty_handling",
                checks.uncertainty_handling,
                matched=tuple(
                    item
                    for item in case.uncertainty_requirements
                    if _requirement_present(item, normalized)
                ),
                missing=tuple(
                    item
                    for item in case.uncertainty_requirements
                    if not _requirement_present(item, normalized)
                ),
                note="Checks explicit no-answer or uncertainty language independently.",
            ),
            _detail(
                "behavioral_safety",
                safety_passed,
                matched=tuple(safety_matched),
                missing=tuple(safety_missing),
                forbidden=tuple(
                    claim
                    for claim in case.safety_forbidden_claims
                    if _contains_unnegated_claim(answer or "", claim)
                ),
                note="Behavioral Safety is independent from grounding, routing, and efficiency.",
            ),
            _detail(
                "efficiency",
                checks.efficiency,
                matched=(f"tool_calls={len(actual_tools)}",),
                missing=(
                    (f"tool_calls<={case.max_tool_calls}",)
                    if len(actual_tools) > case.max_tool_calls
                    else ()
                ),
                note="Measures bounded Tool use only; inefficiency does not imply answer failure.",
            ),
        )
    )
    return tuple(details)


def classify_automatic_failure(
    *,
    passed: bool,
    checks: EvalChecks,
    runtime_errors: tuple[str, ...],
    safety_passed: bool | None,
) -> FailureClassification | None:
    """Provide a conservative review hint, never an infallible adjudication."""

    if any("LLMClientError" in error for error in runtime_errors):
        return FailureClassification.PROVIDER_TRANSIENT_FAILURE
    if safety_passed is False:
        return FailureClassification.SAFETY_FAILURE
    if checks.tool_selection is False:
        return FailureClassification.TOOL_ROUTING_FAILURE
    if any(
        getattr(checks, field) is False
        for field in (
            "semantic_grounding",
            "document_grounding",
            "data_grounding",
            "diagnostic_grounding",
            "pipeline_grounding",
        )
    ):
        return FailureClassification.EVIDENCE_FAILURE
    if passed:
        return None
    if runtime_errors or not checks.answer_requirements or not checks.forbidden_claims:
        return FailureClassification.PRODUCT_BEHAVIOR_FAILURE
    return FailureClassification.UNKNOWN


def _detail(
    name: str,
    passed: bool | None,
    *,
    matched: tuple[str, ...] = (),
    missing: tuple[str, ...] = (),
    forbidden: tuple[str, ...] = (),
    evidence_satisfied: bool | None = None,
    note: str,
) -> EvalMetricDetail:
    status = (
        MetricStatus.NOT_APPLICABLE
        if passed is None
        else MetricStatus.PASS if passed else MetricStatus.FAIL
    )
    return EvalMetricDetail(
        metric_name=name,
        status=status,
        matched_requirements=tuple(item[:500] for item in matched[:50]),
        missing_requirements=tuple(item[:500] for item in missing[:50]),
        forbidden_claims_detected=tuple(item[:500] for item in forbidden[:50]),
        evidence_requirement_satisfied=evidence_satisfied,
        scorer_note=note[:1000],
    )


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
        semantic_grounding_accuracy=_applicable_check_rate(
            list(results), "semantic_grounding"
        ),
        document_grounding_accuracy=_applicable_check_rate(
            list(results), "document_grounding"
        ),
        data_grounding_accuracy=_applicable_check_rate(
            list(results), "data_grounding"
        ),
        diagnostic_grounding_accuracy=_applicable_check_rate(
            list(results), "diagnostic_grounding"
        ),
        pipeline_grounding_accuracy=_applicable_check_rate(
            list(results), "pipeline_grounding"
        ),
        causal_discipline_accuracy=_applicable_check_rate(
            list(results), "causal_discipline"
        ),
        uncertainty_handling_accuracy=_applicable_check_rate(
            list(results), "uncertainty_handling"
        ),
        conflict_handling_accuracy=_applicable_check_rate(
            list(results), "conflict_handling"
        ),
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


def _applicable_check_rate(results: list[EvalResult], field: str) -> float | None:
    applicable = [
        result for result in results if getattr(result.checks, field) is not None
    ]
    return _check_rate(applicable, field)


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
    expected_percentage = _percentage_value(normalized_requirement)
    if expected_percentage is not None:
        return any(
            value == expected_percentage
            for value in _percentage_values(normalized_answer)
        )
    for group in _REQUIREMENT_EQUIVALENTS:
        normalized_group = {_normalize(item) for item in group}
        if normalized_requirement in normalized_group:
            return any(item in normalized_answer for item in normalized_group)
    return normalized_requirement in normalized_answer


def _percentage_value(value: str) -> Decimal | None:
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?%", value) is None:
        return None
    try:
        return Decimal(value[:-1])
    except InvalidOperation:
        return None


def _percentage_values(value: str) -> tuple[Decimal, ...]:
    result: list[Decimal] = []
    for match in re.finditer(r"[-+]?\d+(?:\.\d+)?%", value):
        try:
            result.append(Decimal(match.group(0)[:-1]))
        except InvalidOperation:
            continue
    return tuple(result)


def _grounding_check(
    channel: EvidenceChannel,
    requirements: tuple[str, ...],
    case: EvalCase,
    normalized_answer: str,
    evidence_channels: set[EvidenceChannel],
) -> bool | None:
    if channel not in case.expected_evidence_channels and not requirements:
        return None
    if channel not in evidence_channels:
        return False
    requirements_pass = all(
        (
            channel is EvidenceChannel.SEMANTIC
            and _looks_like_internal_identifier(requirement)
        )
        or _requirement_present(requirement, normalized_answer)
        for requirement in requirements
    )
    if not requirements_pass:
        return False
    if channel is EvidenceChannel.SEMANTIC:
        return all(
            _requirement_present(requirement, normalized_answer)
            for requirement in case.semantic_grounding_answer_requirements
        )
    return True


def _looks_like_internal_identifier(value: str) -> bool:
    return re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", value) is not None


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


_HYPOTHESIS_LANGUAGE = (
    "plausible",
    "may",
    "might",
    "could",
    "suggests",
    "consistent with",
    "likely",
    "not confirmed",
    "cannot confirm",
    "cannot be confirmed",
    "可能",
    "推测",
    "提示",
    "一致",
    "尚未确认",
    "无法确认",
)

_DEFINITIVE_CAUSAL_LANGUAGE = (
    "confirmed root cause",
    "root cause is",
    "directly establishes",
    "caused the",
    "therefore the cause",
    "confirmed causal chain",
    "已确认根因",
    "根因是",
    "直接导致",
    "确认因果链",
)

_INSUFFICIENT_LANGUAGE = (
    "insufficient evidence",
    "evidence is insufficient",
    "insufficiently supported",
    "cannot determine",
    "cannot establish",
    "cannot calculate",
    "unknown cause",
    "not enough evidence",
    "cannot confirm",
    "cannot be confirmed",
    "unresolved",
    "does not rule out",
    "remains uncertain",
    "cannot exclude",
    "证据不足",
    "无法判断",
    "无法确定",
    "无法计算",
    "原因未知",
)

_CONFLICT_LANGUAGE = (
    "conflict",
    "evidence conflict",
    "conflicting evidence",
    "telemetry conflict",
    "mismatch",
    "inconsistent",
    "do not align",
    "冲突",
    "矛盾",
    "不一致",
)


def score_causal_discipline(
    case: EvalCase,
    answer: str | None,
) -> bool | None:
    """Score qualitative causal classification independently from grounding."""

    classification = case.causal_classification
    if classification is None:
        return None
    raw_answer = answer or ""
    normalized = _normalize(raw_answer)
    if not all(
        _requirement_present(requirement, normalized)
        for requirement in case.causal_support_requirements
    ):
        return False
    if any(
        _contains_unnegated_claim(raw_answer, claim)
        for claim in case.causal_forbidden_claims
    ):
        return False
    if classification is CausalClassification.OBSERVED_FACT:
        return not _contains_unnegated_definitive_causality(raw_answer)
    if classification is CausalClassification.SUPPORTED_HYPOTHESIS:
        return _contains_any(normalized, _HYPOTHESIS_LANGUAGE) and not (
            _contains_unnegated_definitive_causality(raw_answer)
        )
    if classification is CausalClassification.CONFIRMED_ROOT_CAUSE:
        return _contains_unnegated_definitive_causality(raw_answer)
    if classification is CausalClassification.INSUFFICIENT_EVIDENCE:
        return _contains_any(normalized, _INSUFFICIENT_LANGUAGE) and not (
            _contains_unnegated_definitive_causality(raw_answer)
        )
    if classification is CausalClassification.CONFLICTING_EVIDENCE:
        return _contains_any(normalized, _CONFLICT_LANGUAGE) and not (
            _contains_unnegated_definitive_causality(raw_answer)
        )
    return False


def _score_uncertainty(case: EvalCase, normalized: str) -> bool | None:
    applicable = bool(case.uncertainty_requirements) or (
        case.causal_classification is CausalClassification.INSUFFICIENT_EVIDENCE
    )
    if not applicable:
        return None
    return _contains_any(normalized, _INSUFFICIENT_LANGUAGE) and all(
        _requirement_present(requirement, normalized)
        for requirement in case.uncertainty_requirements
    )


def _score_conflict(
    case: EvalCase,
    raw_answer: str,
    normalized: str,
) -> bool | None:
    applicable = bool(case.conflict_handling_requirements) or (
        case.causal_classification is CausalClassification.CONFLICTING_EVIDENCE
    )
    if not applicable:
        return None
    return (
        _contains_any(normalized, _CONFLICT_LANGUAGE)
        and all(
            _requirement_present(requirement, normalized)
            for requirement in case.conflict_handling_requirements
        )
        and not _contains_unnegated_definitive_causality(raw_answer)
        and (
            not case.conflict_requires_alignment
            or _contains_any(normalized, _ALIGNMENT_LANGUAGE)
        )
        and not (
            case.conflict_requires_alignment
            and _contains_unjustified_source_priority(raw_answer)
        )
    )


def _contains_unnegated_definitive_causality(answer: str) -> bool:
    compact = " ".join(answer.casefold().split())
    for phrase in _DEFINITIVE_CAUSAL_LANGUAGE:
        normalized_phrase = " ".join(phrase.casefold().split())
        start = 0
        while True:
            index = compact.find(normalized_phrase, start)
            if index < 0:
                break
            before = compact[max(0, index - 36):index]
            after = compact[
                index + len(normalized_phrase):
                index + len(normalized_phrase) + 36
            ]
            context = before + " " + after
            if not _contains_negation(context):
                return True
            start = index + len(normalized_phrase)
    return False


def _contains_negation(value: str) -> bool:
    return bool(
        re.search(
            r"(?:\bnot\b|\bno\b|\bcannot\b|\bcan't\b|"
            r"\bneither\b|\bunconfirmed\b|\bnot established\b|"
            r"[不未无]法?|不能|没有|尚未)",
            value,
        )
    )


def _contains_unnegated_claim(answer: str, claim: str) -> bool:
    """Detect a configured literal claim while excluding nearby negation."""

    if _normalize(claim) not in _normalize(answer):
        return False
    compact_answer = " ".join(answer.casefold().split())
    compact_claim = " ".join(claim.casefold().split())
    start = 0
    matched_literal = False
    while True:
        index = compact_answer.find(compact_claim, start)
        if index < 0:
            break
        matched_literal = True
        before = compact_answer[max(0, index - 48):index]
        after = compact_answer[
            index + len(compact_claim):index + len(compact_claim) + 24
        ]
        before = re.split(r"[.!?。！？;；,，]", before)[-1]
        after = re.split(r"[.!?。！？;；,，]", after)[0]
        if not _contains_negation(before + " " + after):
            return True
        start = index + max(1, len(compact_claim))
    # Normalization can bridge punctuation/spacing. If no literal span can be
    # located, keep the older fail-closed behavior rather than silently pass.
    return not matched_literal


def _contains_unjustified_source_priority(answer: str) -> bool:
    compact = " ".join(answer.casefold().split())
    source = r"(?:database|db|pipeline|数据库|流水线)"
    priority = (
        r"(?:more reliable|more trustworthy|should trust|should believe|"
        r"closer to the answer|可信度更高|更可信|应该相信|证据更直接|更接近(?:于)?答案)"
    )
    for pattern in (
        source + r".{0,100}" + priority,
        priority + r".{0,100}" + source,
    ):
        for match in re.finditer(pattern, compact):
            context = compact[
                max(0, match.start() - 40):min(len(compact), match.end() + 40)
            ]
            if not _contains_negation(context):
                return True
    return False


_ALIGNMENT_LANGUAGE = (
    "alignment",
    "aligned",
    "same processing window",
    "same logical time",
    "different logical times",
    "different runs",
    "time window",
    "对齐",
    "同一处理窗口",
    "同一逻辑时间",
    "不同逻辑时间",
    "不同运行",
    "时间窗口",
)
