"""Bounded single-database PostgreSQL Agent Tool loop."""

import json
import logging
import re
from importlib.resources import files
from time import perf_counter

from data_copilot.agent import (
    AgentResult,
    _ToolCallState,
    _FINAL_SYNTHESIS_FALLBACK,
    _FINAL_SYNTHESIS_INSTRUCTION,
    _final_synthesis_answer,
    _canonical_tool_request,
    _evidence_reuse,
    _EVIDENCE_PREFIXES,
    _messages_with_tool_budget,
    _has_evidence,
    _safe_runtime_failure,
    _safe_tool_error,
)
from data_copilot.config import MAX_TOOL_ROUNDS
from data_copilot.databases import DatabaseRegistry
from data_copilot.documents import (
    BusinessDocumentIndex,
    DocumentEvidenceBuilder,
    DocumentEvidenceFormatter,
)
from data_copilot.diagnostics import (
    DiagnosticEvidence,
    DiagnosticEvidenceFormatter,
    PipelineEvidence,
    PipelineEvidenceFormatter,
    TroubleshootingResources,
)
from data_copilot.errors import (
    AgentExecutionError,
    DataCopilotError,
    DiagnosticComparisonUnavailableError,
    FinalSynthesisError,
    LLMClientError,
    LLMFatalError,
    LLMMalformedResponseError,
    LLMTransientError,
    SemanticAmbiguityError,
    SemanticNotFoundError,
    UnknownToolError,
)
from data_copilot.evidence import EvidenceBuilder, EvidenceFormatter
from data_copilot.execution import PostgresEngine
from data_copilot.llm import LLMClient, LLMMessage, LLMResponse, LLMRole, LLMUsage
from data_copilot.llm.models import ToolDefinition
from data_copilot.semantics import (
    SemanticCatalog,
    SemanticEvidenceBuilder,
    SemanticEvidenceFormatter,
    SemanticResolver,
)
from data_copilot.tools import DatabaseToolDispatcher, TroubleshootingToolSet
from data_copilot.tools.document_context import DocumentRetrievalTool
from data_copilot.tools.semantic_context import SemanticResolutionTool
from data_copilot.runtime import (
    ProviderRetryPolicy,
    RuntimeStage,
    classify_runtime_failure,
    is_nonexecuting_tool_failure,
)


logger = logging.getLogger(__name__)


_RUN_LOCAL_CACHEABLE_DATABASE_TOOLS = frozenset(
    {
        "list_tables",
        "inspect_table",
        "get_relationships",
        SemanticResolutionTool.name,
        DocumentRetrievalTool.name,
        "compare_table_snapshots",
        "inspect_pipeline_run",
        "compare_pipeline_runs",
    }
)
_MAX_REJECTED_TOOL_REQUESTS = 3


_DATABASE_FINAL_SYNTHESIS_INSTRUCTION = (
    _FINAL_SYNTHESIS_INSTRUCTION.replace(
        "the metadata, DATA_EVIDENCE, and safe Tool errors",
        "metadata, SEMANTIC_EVIDENCE, DOCUMENT_EVIDENCE, DATA_EVIDENCE, and "
        "safe Tool errors",
    )
    + " Treat SEMANTIC_EVIDENCE as configured business meaning, "
    "DOCUMENT_EVIDENCE as retrieved explanatory context, and DATA_EVIDENCE as "
    "observed database facts. Do not convert semantic or document content into "
    "observed values, and do not invent a missing definition."
)


class DatabaseCopilotAgent:
    """Run the existing bounded Agent pattern for one PostgreSQL database."""

    def __init__(
        self,
        registry: DatabaseRegistry,
        database_id: str,
        llm_client: LLMClient,
        *,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
        engine: PostgresEngine | None = None,
        evidence_builder: EvidenceBuilder | None = None,
        evidence_formatter: EvidenceFormatter | None = None,
        semantic_catalog: SemanticCatalog | None = None,
        semantic_resolver: SemanticResolver | None = None,
        semantic_evidence_builder: SemanticEvidenceBuilder | None = None,
        semantic_evidence_formatter: SemanticEvidenceFormatter | None = None,
        document_index: BusinessDocumentIndex | None = None,
        document_evidence_builder: DocumentEvidenceBuilder | None = None,
        document_evidence_formatter: DocumentEvidenceFormatter | None = None,
        troubleshooting_resources: TroubleshootingResources | None = None,
        diagnostic_evidence_formatter: DiagnosticEvidenceFormatter | None = None,
        pipeline_evidence_formatter: PipelineEvidenceFormatter | None = None,
        provider_retry_policy: ProviderRetryPolicy | None = None,
    ) -> None:
        if (
            isinstance(max_tool_rounds, bool)
            or not isinstance(max_tool_rounds, int)
            or max_tool_rounds < 1
        ):
            raise AgentExecutionError("max_tool_rounds must be a positive integer.")
        database = registry.get(database_id)
        self._llm_client = llm_client
        self._dispatcher = DatabaseToolDispatcher(
            registry, database_id, engine=engine
        )
        self._evidence_builder = evidence_builder or EvidenceBuilder()
        self._evidence_formatter = evidence_formatter or EvidenceFormatter()
        if semantic_catalog is None and any(
            resource is not None
            for resource in (
                semantic_resolver,
                semantic_evidence_builder,
                semantic_evidence_formatter,
            )
        ):
            raise AgentExecutionError(
                "Semantic helpers require a configured SemanticCatalog."
            )
        if document_index is None and any(
            resource is not None
            for resource in (
                document_evidence_builder,
                document_evidence_formatter,
            )
        ):
            raise AgentExecutionError(
                "Document helpers require a configured BusinessDocumentIndex."
            )
        self._semantic_tool = (
            SemanticResolutionTool(
                semantic_catalog,
                resolver=semantic_resolver,
                evidence_builder=semantic_evidence_builder,
            )
            if semantic_catalog is not None
            else None
        )
        self._semantic_evidence_formatter = None
        if self._semantic_tool is not None:
            self._semantic_evidence_formatter = (
                semantic_evidence_formatter or SemanticEvidenceFormatter()
            )
        self._document_tool = (
            DocumentRetrievalTool(
                document_index,
                evidence_builder=document_evidence_builder,
            )
            if document_index is not None
            else None
        )
        self._document_evidence_formatter = None
        if self._document_tool is not None:
            self._document_evidence_formatter = (
                document_evidence_formatter or DocumentEvidenceFormatter()
            )
        if troubleshooting_resources is None and any(
            formatter is not None
            for formatter in (
                diagnostic_evidence_formatter,
                pipeline_evidence_formatter,
            )
        ):
            raise AgentExecutionError(
                "Troubleshooting formatters require configured resources."
            )
        self._troubleshooting_tools = (
            TroubleshootingToolSet(database_id, troubleshooting_resources)
            if troubleshooting_resources is not None
            and troubleshooting_resources.has_capabilities
            else None
        )
        self._diagnostic_evidence_formatter = None
        self._pipeline_evidence_formatter = None
        if self._troubleshooting_tools is not None:
            self._diagnostic_evidence_formatter = (
                diagnostic_evidence_formatter or DiagnosticEvidenceFormatter()
            )
            self._pipeline_evidence_formatter = (
                pipeline_evidence_formatter or PipelineEvidenceFormatter()
            )
        optional_schemas = tuple(
            tool.schema
            for tool in (self._semantic_tool, self._document_tool)
            if tool is not None
        )
        troubleshooting_schemas = (
            self._troubleshooting_tools.schemas
            if self._troubleshooting_tools is not None
            else ()
        )
        optional_schemas += troubleshooting_schemas
        self._tool_schemas = self._dispatcher.schemas + optional_schemas
        self._allowed_tool_names = self._dispatcher.allowed_tool_names | frozenset(
            schema.name for schema in optional_schemas
        )
        self._max_tool_rounds = max_tool_rounds
        self._provider_retry_policy = provider_retry_policy or ProviderRetryPolicy()
        self._messages: list[LLMMessage] = [
            LLMMessage(
                role=LLMRole.SYSTEM,
                content=_database_system_prompt(
                    database.to_public_metadata().model_dump(mode="json"),
                    optional_tool_names=tuple(
                        schema.name for schema in optional_schemas
                    ),
                    troubleshooting_metadata=(
                        troubleshooting_resources.to_public_metadata()
                        if self._troubleshooting_tools is not None
                        and troubleshooting_resources is not None
                        else None
                    ),
                ),
            )
        ]
        self._final_synthesis_instruction = _DATABASE_FINAL_SYNTHESIS_INSTRUCTION
        if self._troubleshooting_tools is not None:
            self._final_synthesis_instruction += (
                " Treat DIAGNOSTIC_EVIDENCE as observed snapshot/drift facts and "
                "PIPELINE_EVIDENCE as observed run facts. Separate observed facts, "
                "hypotheses, confirmed cause, and insufficient evidence; correlation "
                "alone is not causation."
            )

    @property
    def messages(self) -> tuple[LLMMessage, ...]:
        return tuple(self._messages)

    def ask(self, question: str) -> AgentResult:
        if not isinstance(question, str) or not question.strip():
            raise AgentExecutionError("Question must be a non-empty string.")
        self._messages.append(LLMMessage(role=LLMRole.USER, content=question))
        tool_calls_used = 0
        rounds = 0
        usage: LLMUsage | None = None
        evidence_cache: dict[tuple[str, str], tuple[str, int]] = {}
        rejected_tool_requests = 0

        while True:
            tool_schemas = self._tool_schemas_for_question(question)
            try:
                response = self._complete(
                    tool_calls_remaining=self._max_tool_rounds - tool_calls_used,
                    tool_schemas=tool_schemas,
                )
            except LLMClientError as exc:
                if _has_evidence(self._messages):
                    raise AgentExecutionError(
                        "Execution stopped after partial Evidence was collected; "
                        "no unsupported final answer was produced."
                    ) from exc
                raise
            if response.usage is not None:
                usage = response.usage if usage is None else usage + response.usage
            rounds += 1
            if response.tool_calls:
                # Tool results can change which action is useful next. Execute only
                # the first ordered call and require a fresh evidence-aware decision;
                # later calls from the same completion are intentionally discarded.
                tool_call = response.tool_calls[0]
                self._messages.append(
                    LLMMessage(
                        role=LLMRole.ASSISTANT,
                        # Evidence, not Tool-call prose, is the factual state.
                        content=None,
                        tool_calls=(tool_call,),
                    )
                )
                cache_key = _canonical_tool_request(
                    tool_call.name, tool_call.arguments
                )
                cacheable = tool_call.name in _RUN_LOCAL_CACHEABLE_DATABASE_TOOLS
                cached = (
                    evidence_cache.get(cache_key)
                    if cacheable and cache_key is not None
                    else None
                )
                if cached is not None:
                    original_call_id, avoided_chars = cached
                    self._messages.append(
                        LLMMessage(
                            role=LLMRole.TOOL,
                            content=_evidence_reuse(
                                tool_name=tool_call.name,
                                original_tool_call_id=original_call_id,
                                avoided_chars=avoided_chars,
                            ),
                            tool_call_id=tool_call.call_id,
                        )
                    )
                    logger.info(
                        "tool_call name=%s status=reused round=%d avoided_chars=%d",
                        tool_call.name,
                        tool_calls_used + 1,
                        avoided_chars,
                    )
                    return self._final_synthesis(
                        tool_calls_used=tool_calls_used,
                        rounds=rounds,
                        usage=usage,
                    )
                state = self._execute_tool_call(
                    tool_call.call_id,
                    tool_call.name,
                    tool_call.arguments,
                    tool_calls_used + 1,
                    current_user_message=question,
                )
                if state.executed:
                    tool_calls_used += 1
                else:
                    rejected_tool_requests += 1
                latest_content = self._messages[-1].content or ""
                if (
                    cacheable
                    and cache_key is not None
                    and state.evidence_produced
                    and latest_content.startswith(_EVIDENCE_PREFIXES)
                ):
                    evidence_cache[cache_key] = (
                        tool_call.call_id,
                        len(latest_content),
                    )
                if (
                    state.terminal
                    or tool_calls_used == self._max_tool_rounds
                    or rejected_tool_requests >= _MAX_REJECTED_TOOL_REQUESTS
                ):
                    return self._final_synthesis(
                        tool_calls_used=tool_calls_used,
                        rounds=rounds,
                        usage=usage,
                    )
                continue

            answer = (response.text or "").strip()
            if not answer:
                raise AgentExecutionError(
                    "The LLM returned neither a Tool call nor a final answer."
                )
            self._messages.append(LLMMessage(role=LLMRole.ASSISTANT, content=answer))
            return AgentResult(
                answer=answer,
                tool_calls_used=tool_calls_used,
                rounds=rounds,
                usage=usage,
            )

    def _complete(
        self,
        *,
        tool_calls_remaining: int,
        tool_schemas: tuple[ToolDefinition, ...],
    ) -> LLMResponse:
        messages = _messages_with_tool_budget(
            self._messages, tool_calls_remaining=tool_calls_remaining
        )
        return self._provider_complete(messages, tool_schemas)

    def _provider_complete(
        self,
        messages: tuple[LLMMessage, ...],
        tools: tuple[ToolDefinition, ...],
    ) -> LLMResponse:
        retries = 0
        while True:
            try:
                response = self._llm_client.complete(messages, tools)
                if response.text is None and not response.tool_calls:
                    raise LLMMalformedResponseError(
                        "The model provider returned no usable decision."
                    )
                return response
            except LLMTransientError:
                if retries >= self._provider_retry_policy.max_retries:
                    raise
                retries += 1
            except LLMClientError:
                raise
            except Exception as exc:
                raise LLMFatalError("The LLM client failed safely.") from exc

    def _tool_schemas_for_question(
        self,
        question: str,
    ) -> tuple[ToolDefinition, ...]:
        """Conservatively narrow capabilities only for high-confidence routes."""

        physical_database_only = _explicitly_requests_physical_database_only(
            question
        )
        excluded_context_tools = _explicit_context_tool_exclusions(question)
        available = {
            schema.name: schema
            for schema in self._tool_schemas
            if schema.name not in excluded_context_tools
        }
        has_semantic = self._has_evidence("SEMANTIC_EVIDENCE\n")
        has_document = self._has_evidence("DOCUMENT_EVIDENCE\n")
        has_data = self._has_evidence("DATA_EVIDENCE\n")
        has_query_result = self._has_data_operation("execute_read_query")
        has_diagnostic = self._has_evidence("DIAGNOSTIC_EVIDENCE\n")
        has_pipeline = self._has_evidence("PIPELINE_EVIDENCE\n")

        def select(names: frozenset[str]) -> tuple[ToolDefinition, ...]:
            return tuple(
                schema
                for schema in self._tool_schemas
                if schema.name in names and schema.name in available
            )

        if _explicitly_missing_comparison_baseline(question):
            return ()
        if physical_database_only:
            if has_query_result:
                return ()
            return select(self._dispatcher.allowed_tool_names)
        if (
            _is_definition_only_question(question)
            and SemanticResolutionTool.name in available
        ):
            if has_semantic:
                return ()
            names = {SemanticResolutionTool.name}
            if (
                self._document_tool is not None
                and _requests_explicit_definition_rationale(question)
            ):
                names.add(DocumentRetrievalTool.name)
            return select(frozenset(names))
        if (
            self._semantic_tool is not None
            and self._document_tool is not None
            and _is_policy_explanation_question(question)
        ):
            names: set[str] = set()
            if not has_semantic:
                names.add(SemanticResolutionTool.name)
            if not has_document:
                names.add(DocumentRetrievalTool.name)
            return select(frozenset(names))
        if _is_simple_database_count(question):
            if has_data:
                return ()
            return select(self._dispatcher.allowed_tool_names)
        if (
            _is_metric_value_question(question)
            and SemanticResolutionTool.name in available
        ):
            if not has_semantic:
                return select(frozenset({SemanticResolutionTool.name}))
            if has_query_result:
                return ()
            return select(
                frozenset(
                    {"inspect_table", "get_relationships", "execute_read_query"}
                )
            )
        if self._troubleshooting_tools is not None:
            troubleshooting_names = self._troubleshooting_tools.allowed_tool_names
            diagnostic_names = troubleshooting_names & frozenset(
                {"collect_table_diagnostics", "compare_table_snapshots"}
            )
            pipeline_names = troubleshooting_names & frozenset(
                {"inspect_pipeline_run", "compare_pipeline_runs"}
            )
            wants_diagnostics = _is_explicit_technical_diagnostic_question(question)
            wants_pipeline = _is_pipeline_question(question)
            if wants_diagnostics or wants_pipeline:
                selected = frozenset()
                if wants_diagnostics and not has_diagnostic:
                    selected |= diagnostic_names
                if wants_pipeline and not has_pipeline:
                    selected |= pipeline_names
                if selected:
                    return select(selected)
                return ()
        # Uncertain requests fail open to the full registered capability set.
        return tuple(available.values())

    def _has_evidence(self, prefix: str) -> bool:
        return any(
            message.role is LLMRole.TOOL
            and (message.content or "").startswith(prefix)
            for message in self._messages
        )

    def _has_data_operation(self, operation: str) -> bool:
        for message in self._messages:
            content = message.content or ""
            if message.role is not LLMRole.TOOL or not content.startswith(
                "DATA_EVIDENCE\n"
            ):
                continue
            try:
                payload = json.loads(content.split("\n", 1)[1])
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("operation") == operation:
                return True
        return False

    def _final_synthesis(
        self,
        *,
        tool_calls_used: int,
        rounds: int,
        usage: LLMUsage | None,
    ) -> AgentResult:
        self._messages.append(
            LLMMessage(
                role=LLMRole.SYSTEM,
                content=self._final_synthesis_instruction,
            )
        )
        messages = _messages_with_tool_budget(
            self._messages, tool_calls_remaining=0
        )
        try:
            response = self._provider_complete(messages, ())
        except LLMClientError as exc:
            raise FinalSynthesisError(
                "Final synthesis could not complete; collected Evidence remains "
                "available, but no final analytical answer was produced."
            ) from exc
        if response.usage is not None:
            usage = response.usage if usage is None else usage + response.usage
        answer = _final_synthesis_answer(response)
        self._messages.append(LLMMessage(role=LLMRole.ASSISTANT, content=answer))
        return AgentResult(
            answer=answer,
            tool_calls_used=tool_calls_used,
            rounds=rounds + 1,
            usage=usage,
        )

    def _execute_tool_call(
        self,
        call_id: str,
        name: str,
        arguments: str,
        tool_round: int,
        *,
        current_user_message: str,
    ) -> _ToolCallState:
        started = perf_counter()
        row_count: int | None = None
        plan_node_count: int | None = None
        truncated: bool | None = None
        evidence_channel: str | None = None
        terminal_diagnostic_state = False
        try:
            explicitly_excluded = _explicit_context_tool_exclusions(
                current_user_message
            )
            physical_database_only = (
                _explicitly_requests_physical_database_only(
                    current_user_message
                )
            )
            if name in explicitly_excluded or (
                physical_database_only
                and name not in self._dispatcher.allowed_tool_names
            ):
                raise UnknownToolError(
                    "The requested Tool is unavailable for this request."
                )
            if name == SemanticResolutionTool.name and self._semantic_tool is not None:
                semantic_evidence = self._semantic_tool.invoke(
                    arguments,
                    current_user_message=current_user_message,
                )
                if self._semantic_evidence_formatter is None:
                    raise AgentExecutionError(
                        "Semantic evidence formatter is unavailable."
                    )
                truncated = semantic_evidence.truncated
                evidence_channel = "SEMANTIC_EVIDENCE"
                content = self._semantic_evidence_formatter.format(semantic_evidence)
            elif name == DocumentRetrievalTool.name and self._document_tool is not None:
                document_evidence = self._document_tool.invoke(arguments)
                if self._document_evidence_formatter is None:
                    raise AgentExecutionError(
                        "Document evidence formatter is unavailable."
                    )
                truncated = document_evidence.truncated
                evidence_channel = "DOCUMENT_EVIDENCE"
                content = self._document_evidence_formatter.format(document_evidence)
            elif (
                self._troubleshooting_tools is not None
                and name in self._troubleshooting_tools.allowed_tool_names
            ):
                troubleshooting_evidence = self._troubleshooting_tools.dispatch(
                    name,
                    arguments,
                )
                truncated = troubleshooting_evidence.truncated
                if isinstance(troubleshooting_evidence, DiagnosticEvidence):
                    evidence_channel = "DIAGNOSTIC_EVIDENCE"
                    if self._diagnostic_evidence_formatter is None:
                        raise AgentExecutionError(
                            "Diagnostic evidence formatter is unavailable."
                        )
                    content = self._diagnostic_evidence_formatter.format(
                        troubleshooting_evidence
                    )
                elif isinstance(troubleshooting_evidence, PipelineEvidence):
                    evidence_channel = "PIPELINE_EVIDENCE"
                    if self._pipeline_evidence_formatter is None:
                        raise AgentExecutionError(
                            "Pipeline evidence formatter is unavailable."
                        )
                    content = self._pipeline_evidence_formatter.format(
                        troubleshooting_evidence
                    )
                else:
                    raise AgentExecutionError(
                        "Troubleshooting Tool returned unsupported evidence."
                    )
            else:
                result = self._dispatcher.dispatch(name, arguments)
                row_count = getattr(result, "row_count", None)
                plan_node_count = getattr(result, "node_count", None)
                truncated = getattr(result, "truncated", None)
                evidence = self._evidence_builder.build(result)
                evidence_channel = "DATA_EVIDENCE"
                content = self._evidence_formatter.format(evidence)
            logger.info(
                "tool_call name=%s status=success round=%d duration_ms=%.3f "
                "row_count=%s plan_node_count=%s truncated=%s evidence_channel=%s",
                name if name in self._allowed_tool_names else "unsupported",
                tool_round,
                (perf_counter() - started) * 1000,
                row_count,
                plan_node_count,
                truncated,
                evidence_channel,
            )
            state = _ToolCallState(executed=True, evidence_produced=True)
        except DataCopilotError as exc:
            content = _safe_tool_error(exc)
            executed = not is_nonexecuting_tool_failure(exc)
            terminal_diagnostic_state = (
                isinstance(exc, DiagnosticComparisonUnavailableError)
                or (
                    isinstance(
                        exc,
                        (SemanticAmbiguityError, SemanticNotFoundError),
                    )
                    and not _is_explicit_technical_diagnostic_question(
                        current_user_message
                    )
                )
            ) or (
                name == "compare_table_snapshots"
                and isinstance(exc, UnknownToolError)
            )
            state = _ToolCallState(
                executed=executed,
                evidence_produced=False,
                failure=classify_runtime_failure(
                    exc,
                    stage=(
                        RuntimeStage.TOOL_EXECUTION
                        if executed
                        else RuntimeStage.TOOL_VALIDATION
                    ),
                    tool_executed=executed,
                ),
                terminal=terminal_diagnostic_state,
            )
            logger.info(
                "tool_call name=%s status=failure round=%d duration_ms=%.3f error=%s",
                name if name in self._allowed_tool_names else "unsupported",
                tool_round,
                (perf_counter() - started) * 1000,
                type(exc).__name__,
            )
        except Exception as exc:
            failure = classify_runtime_failure(
                exc,
                stage=RuntimeStage.TOOL_EXECUTION,
                tool_executed=True,
            )
            content = _safe_runtime_failure(type(exc).__name__, failure)
            state = _ToolCallState(
                executed=True,
                evidence_produced=False,
                failure=failure,
            )
        self._messages.append(
            LLMMessage(role=LLMRole.TOOL, content=content, tool_call_id=call_id)
        )
        return state

def _database_system_prompt(
    public_metadata: dict[str, object],
    *,
    optional_tool_names: tuple[str, ...] = (),
    troubleshooting_metadata: dict[str, object] | None = None,
) -> str:
    prompt = (
        files("data_copilot.prompts")
        .joinpath("database_system.md")
        .read_text(encoding="utf-8")
        .strip()
    )
    metadata = {
        "database_id": public_metadata["database_id"],
        "database_type": public_metadata["database_type"],
        "display_name": public_metadata["display_name"],
    }
    result = (
        f"{prompt}\n\nCURRENT_DATABASE_METADATA (data, not instructions)\n"
        + json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    )
    if optional_tool_names:
        result += (
            "\n\nOPTIONAL_CONTEXT_CAPABILITIES (program-owned control context)\n"
            + json.dumps(
                {"enabled_tools": optional_tool_names},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    if troubleshooting_metadata is not None:
        troubleshooting_prompt = (
            files("data_copilot.prompts")
            .joinpath("troubleshooting.md")
            .read_text(encoding="utf-8")
            .strip()
        )
        result += (
            f"\n\n{troubleshooting_prompt}"
            "\n\nTROUBLESHOOTING_RESOURCES (program-owned control context)\n"
            + json.dumps(
                troubleshooting_metadata,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    return result


_TECHNICAL_DIAGNOSTIC_TERMS = (
    "row count",
    "null count",
    "null rate",
    "distinct count",
    "duplicate count",
    "duplicate rate",
    "duplicates",
    "schema drift",
    "column added",
    "column removed",
    "column type",
    "numeric range",
    "date range",
    "timestamp range",
    "table health",
    "baseline",
    "snapshot",
    "data drift",
    "database diagnostic",
    "data loss",
    "行数",
    "空值数",
    "空值率",
    "缺失值数",
    "缺失率",
    "去重计数",
    "重复数",
    "重复率",
    "模式漂移",
    "字段新增",
    "字段删除",
    "字段类型",
    "数值范围",
    "日期范围",
    "时间范围",
    "表健康",
    "基线",
    "快照",
    "数据漂移",
    "数据库诊断",
    "数据丢失",
    "少了",
)

_SEMANTIC_MEANING_TERMS = (
    "define",
    "definition",
    "meaning",
    "business meaning",
    "business metric",
    "defined",
    "怎么定义",
    "如何定义",
    "正式定义",
    "业务定义",
    "业务含义",
    "指标口径",
    "口径",
)

_VALUE_OR_ANALYSIS_TERMS = (
    "how many",
    "value",
    "calculate",
    "trend",
    "by month",
    "by day",
    "compare",
    "breakdown",
    "highest",
    "top",
    "多少",
    "数值",
    "计算",
    "趋势",
    "每月",
    "每个月",
    "每天",
    "对比",
    "分组",
    "最高",
)

_BUSINESS_METRIC_TERMS = (
    "metric",
    "revenue",
    "sales",
    "churn",
    "arpu",
    "profit",
    "active customer",
    "cancelled order",
    "指标",
    "销售额",
    "收入",
    "营收",
    "流失",
    "利润",
    "活跃客户",
    "取消订单",
)

_POLICY_OR_RATIONALE_TERMS = (
    "why",
    "policy",
    "rationale",
    "history",
    "why defined",
    "规则",
    "政策",
    "原因说明",
    "历史",
    "为什么这样定义",
    "为什么",
)

_PIPELINE_TERMS = (
    "pipeline",
    "run_id",
    "pipeline_id",
    "pipeline run",
    "job",
    "step",
    "telemetry",
    "log",
    "load_",
    "extract_",
    "transform_",
    "运行",
    "任务",
    "步骤",
    "遥测",
    "日志",
    "失败",
)

_PHYSICAL_DATABASE_ONLY_PATTERNS = (
    r"\bphysical\s+(?:database\s+)?(?:columns?|fields?|schema)\s+only\b",
    r"\bdatabase\s+(?:physical\s+)?(?:columns?|fields?|schema)\s+only\b",
    r"\b(?:use|using)\s+(?:the\s+)?physical\s+(?:database\s+)?"
    r"(?:columns?|fields?|schema)\s+only\b",
    r"\b(?:use|using)\s+(?:the\s+)?database\s+(?:physical\s+)?"
    r"(?:columns?|fields?|schema)\s+only\b",
    r"\b(?:use|using)\s+only\s+(?:the\s+)?(?:physical\s+)?"
    r"(?:database\s+)?(?:columns?|fields?|schema)\b",
)
_PHYSICAL_DATABASE_ONLY_TERMS = (
    "仅使用物理字段",
    "只使用物理字段",
    "仅使用物理列",
    "只使用物理列",
    "仅使用数据库字段",
    "只使用数据库字段",
    "仅使用数据库列",
    "只使用数据库列",
    "仅使用数据库物理字段",
    "只使用数据库物理字段",
    "仅使用数据库物理列",
    "只使用数据库物理列",
)
_SEMANTIC_EXCLUSION_PATTERNS = (
    r"\b(?:do\s+not|don't|dont)\s+use\s+(?:the\s+)?semantic\s+"
    r"(?:definitions?|layer|tools?)\b",
    r"\bwithout\s+(?:using\s+)?(?:the\s+)?semantic\s+"
    r"(?:definitions?|layer|tools?)\b",
)
_SEMANTIC_EXCLUSION_TERMS = (
    "不使用 semantic layer",
    "不要使用 semantic layer",
    "不使用语义层",
    "不要使用语义层",
    "不使用语义定义",
    "不要使用语义定义",
    "不使用业务定义",
    "不要使用业务定义",
)
_DOCUMENT_EXCLUSION_PATTERNS = (
    r"\b(?:do\s+not|don't|dont)\s+(?:use|retrieve)\s+(?:the\s+)?"
    r"documents?\b",
    r"\bwithout\s+(?:using\s+|retrieving\s+)?(?:the\s+)?documents?\b",
)
_DOCUMENT_EXCLUSION_TERMS = (
    "不使用文档",
    "不要使用文档",
    "不检索文档",
    "不要检索文档",
)


def _explicitly_requests_physical_database_only(question: str) -> bool:
    """Read a physical-only constraint from the current user request only."""

    normalized = " ".join(question.casefold().split())
    return any(
        re.search(pattern, normalized) is not None
        for pattern in _PHYSICAL_DATABASE_ONLY_PATTERNS
    ) or any(term in normalized for term in _PHYSICAL_DATABASE_ONLY_TERMS)


def _explicit_context_tool_exclusions(question: str) -> frozenset[str]:
    """Return explicit semantic/document exclusions from the user request."""

    normalized = " ".join(question.casefold().split())
    physical_database_only = _explicitly_requests_physical_database_only(
        question
    )
    excluded: set[str] = set()
    if physical_database_only or any(
        re.search(pattern, normalized) is not None
        for pattern in _SEMANTIC_EXCLUSION_PATTERNS
    ) or any(term in normalized for term in _SEMANTIC_EXCLUSION_TERMS):
        excluded.add(SemanticResolutionTool.name)
    if physical_database_only or any(
        re.search(pattern, normalized) is not None
        for pattern in _DOCUMENT_EXCLUSION_PATTERNS
    ) or any(term in normalized for term in _DOCUMENT_EXCLUSION_TERMS):
        excluded.add(DocumentRetrievalTool.name)
    return frozenset(excluded)


def _is_explicit_technical_diagnostic_question(question: str) -> bool:
    normalized = " ".join(question.casefold().replace("_", " ").split())
    return (
        any(term in normalized for term in _TECHNICAL_DIAGNOSTIC_TERMS)
        and not any(term in normalized for term in _SEMANTIC_MEANING_TERMS)
    )


def _is_definition_only_question(question: str) -> bool:
    normalized = " ".join(question.casefold().replace("_", " ").split())
    return any(term in normalized for term in _SEMANTIC_MEANING_TERMS) and not any(
        term in normalized for term in _VALUE_OR_ANALYSIS_TERMS
    )


def _requests_policy_or_rationale(question: str) -> bool:
    normalized = " ".join(question.casefold().replace("_", " ").split())
    return any(term in normalized for term in _POLICY_OR_RATIONALE_TERMS)


def _requests_explicit_definition_rationale(question: str) -> bool:
    normalized = " ".join(question.casefold().replace("_", " ").split())
    return any(
        term in normalized
        for term in (
            "policy",
            "rationale",
            "history",
            "why defined",
            "规则",
            "政策",
            "原因说明",
            "历史",
            "为什么这样定义",
        )
    )


def _is_policy_explanation_question(question: str) -> bool:
    normalized = " ".join(question.casefold().replace("_", " ").split())
    return (
        _requests_policy_or_rationale(question)
        and any(term in normalized for term in _BUSINESS_METRIC_TERMS)
        and not _is_explicit_technical_diagnostic_question(question)
        and not _is_pipeline_question(question)
        and not any(term in normalized for term in _VALUE_OR_ANALYSIS_TERMS)
    )


def _is_metric_value_question(question: str) -> bool:
    normalized = " ".join(question.casefold().replace("_", " ").split())
    return any(term in normalized for term in _BUSINESS_METRIC_TERMS) and any(
        term in normalized for term in _VALUE_OR_ANALYSIS_TERMS
    )


def _is_simple_database_count(question: str) -> bool:
    normalized = " ".join(question.casefold().replace("_", " ").split())
    count_requested = any(
        term in normalized
        for term in ("how many rows", "row count", "count rows", "多少行", "行数")
    )
    investigation = any(
        term in normalized
        for term in (
            "baseline",
            "snapshot",
            "drift",
            "drop",
            "change",
            "cause",
            "基线",
            "快照",
            "漂移",
            "下降",
            "变化",
            "原因",
        )
    )
    return count_requested and not investigation and not _is_pipeline_question(question)


def _is_pipeline_question(question: str) -> bool:
    normalized = " ".join(question.casefold().split())
    return any(term in normalized for term in _PIPELINE_TERMS)


def _explicitly_missing_comparison_baseline(question: str) -> bool:
    normalized = " ".join(question.casefold().split())
    missing = any(
        term in normalized
        for term in ("without a baseline", "no baseline", "没有 baseline", "没有基线")
    )
    current_only = any(
        term in normalized
        for term in ("only the current", "只有当前", "仅有当前")
    )
    return missing or (current_only and ("baseline" in normalized or "基线" in normalized))
