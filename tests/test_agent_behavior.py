import json
from pathlib import Path

import pytest

from data_copilot.agent import DataCopilotAgent
from data_copilot.datasets import DatasetRegistry
from data_copilot.llm import FakeLLMClient, LLMResponse, LLMToolCall
from data_copilot.tools import ToolDispatcher


PROJECT_ROOT = Path(__file__).parents[1]


def _tool_call(name: str, arguments: object) -> LLMResponse:
    return LLMResponse(
        tool_calls=(
            LLMToolCall(
                call_id=f"call_{name}",
                name=name,
                arguments=json.dumps(arguments),
            ),
        )
    )


@pytest.fixture
def orders_dataset() -> tuple[DatasetRegistry, str]:
    path = PROJECT_ROOT / "tests/fixtures/orders_demo.csv"
    registry = DatasetRegistry(allowed_roots=[path.parent])
    dataset = registry.register(path)
    return registry, dataset.dataset_id


def test_behavior_prompt_covers_capability_semantics_efficiency_and_evidence_reuse(
    orders_dataset: tuple[DatasetRegistry, str],
) -> None:
    registry, dataset_id = orders_dataset
    client = FakeLLMClient([LLMResponse(text="Ready.")])

    DataCopilotAgent(registry, dataset_id, client).ask("Hello")

    prompt = " ".join((client.requests[0][0][0].content or "").split())
    for required_guidance in (
        "never present a numeric forecast",
        "inspect the schema once",
        "stop calling Tools",
        "Never silently choose a business definition",
        "never repeat an equivalent Tool call",
        "combine all useful metrics, dimensions, filters, and sorting",
        "do not call any data Tool unless the user also explicitly asks",
        "call aggregate_dataset directly without inspect or profile preflight",
        "call check_data_quality directly",
    ):
        assert required_guidance in prompt


def test_tool_descriptions_route_each_evidence_shape_directly(
    orders_dataset: tuple[DatasetRegistry, str],
) -> None:
    registry, dataset_id = orders_dataset
    descriptions = {
        schema.name: schema.description.casefold()
        for schema in ToolDispatcher(registry, dataset_id).schemas
    }

    assert "schema" in descriptions["inspect_dataset"]
    assert "distribution" in descriptions["profile_dataset"]
    assert "record-level examples" in descriptions["sample_dataset"]
    assert "row lookup" in descriptions["filter_dataset"]
    assert "grouped" in descriptions["aggregate_dataset"]
    assert "data-quality" in descriptions["check_data_quality"]
    assert "without inspect or profile preflight" in descriptions["aggregate_dataset"]
    assert "only tool" in descriptions["check_data_quality"]


def test_forecasting_refuses_formal_prediction_without_tool_call(
    orders_dataset: tuple[DatasetRegistry, str],
) -> None:
    registry, dataset_id = orders_dataset
    client = FakeLLMClient(
        [
            LLMResponse(
                text=(
                    "当前六个本地数据工具不具备预测能力，因此无法可靠给出"
                    "正式预测。已有历史 Evidence 只能描述历史变化，不能包装成"
                    "模型预测。"
                )
            )
        ]
    )

    result = DataCopilotAgent(registry, dataset_id, client).ask(
        "预测下个月 completed 销售额是多少？"
    )

    assert result.tool_calls_used == 0
    assert result.rounds == 1
    assert "预测能力" in result.answer
    assert "1050" not in result.answer


def test_missing_concept_stops_after_one_schema_inspection(
    orders_dataset: tuple[DatasetRegistry, str],
) -> None:
    registry, dataset_id = orders_dataset
    client = FakeLLMClient(
        [
            _tool_call("inspect_dataset", {}),
            LLMResponse(
                text=(
                    "无法可靠回答：schema 中没有 city、profit 或 cost "
                    "字段，因此不能计算城市利润率。"
                )
            ),
        ]
    )

    result = DataCopilotAgent(registry, dataset_id, client).ask(
        "哪个城市利润率最高？"
    )

    assert result.tool_calls_used == 1
    assert result.rounds == 2
    requested_tools = [
        call.name
        for message in client.requests[-1][0]
        for call in message.tool_calls
    ]
    assert requested_tools == ["inspect_dataset"]
    assert "无法可靠回答" in result.answer


def test_ambiguous_business_metric_asks_for_definition_before_computing(
    orders_dataset: tuple[DatasetRegistry, str],
) -> None:
    registry, dataset_id = orders_dataset
    client = FakeLLMClient(
        [
            LLMResponse(
                text=(
                    "请先确认销售额口径：应只统计 completed，还是包含其他"
                    "状态？不同定义会改变结果。"
                )
            )
        ]
    )

    result = DataCopilotAgent(registry, dataset_id, client).ask(
        "每个月销售额是多少？"
    )

    assert result.tool_calls_used == 0
    assert "口径" in result.answer
    assert "completed" in result.answer


def test_simple_grouped_numeric_question_uses_only_one_aggregate(
    orders_dataset: tuple[DatasetRegistry, str],
) -> None:
    registry, dataset_id = orders_dataset
    arguments = {
        "dimensions": [
            {"name": "region_name", "column": "region", "time_grain": None}
        ],
        "metrics": [
            {"name": "avg_amount", "function": "avg", "column": "amount"}
        ],
        "filters": [
            {"column": "status", "operator": "eq", "value": "completed"}
        ],
        "order_by": [{"field": "avg_amount", "direction": "desc"}],
        "limit": 4,
    }
    client = FakeLLMClient(
        [
            _tool_call("aggregate_dataset", arguments),
            LLMResponse(text="West 的 completed 平均 amount 最高，为 120。"),
        ]
    )

    result = DataCopilotAgent(registry, dataset_id, client).ask(
        "按 region 比较 completed 记录的平均 amount。"
    )

    assert result.tool_calls_used == 1
    assert result.rounds == 2
    assert "West" in result.answer
    requested_tools = [
        call.name
        for message in client.requests[-1][0]
        for call in message.tool_calls
    ]
    assert requested_tools == ["aggregate_dataset"]


def test_explicit_quality_question_uses_only_quality_tool(
    orders_dataset: tuple[DatasetRegistry, str],
) -> None:
    registry, dataset_id = orders_dataset
    client = FakeLLMClient(
        [
            _tool_call("check_data_quality", {"columns": None}),
            LLMResponse(
                text="发现 1 个缺失值、1 条完全重复行和 1 个 amount 负值 -20。"
            ),
        ]
    )

    result = DataCopilotAgent(registry, dataset_id, client).ask(
        "这个数据集有什么明显的数据质量问题？"
    )

    requested_tools = [
        call.name
        for message in client.requests[-1][0]
        for call in message.tool_calls
    ]
    assert result.tool_calls_used == 1
    assert result.rounds == 2
    assert requested_tools == ["check_data_quality"]


def test_root_cause_investigation_combines_evidence_within_five_calls(
    orders_dataset: tuple[DatasetRegistry, str],
) -> None:
    registry, dataset_id = orders_dataset
    arguments = {
        "dimensions": [
            {"name": "month", "column": "created_at", "time_grain": "month"},
            {"name": "order_status", "column": "status", "time_grain": None},
        ],
        "metrics": [
            {"name": "order_count", "function": "count", "column": None},
            {"name": "total_amount", "function": "sum", "column": "amount"},
            {"name": "average_amount", "function": "avg", "column": "amount"},
        ],
        "filters": [],
        "order_by": [
            {"field": "month", "direction": "asc"},
            {"field": "order_status", "direction": "asc"},
        ],
        "limit": 20,
    }
    client = FakeLLMClient(
        [
            _tool_call("aggregate_dataset", arguments),
            LLMResponse(
                text=(
                    "可观察到 3 月 completed 数从 10 降到 5，而平均金额从 "
                    "105 仅变为 104；这支持订单数减少是贡献因素，但不能确认"
                    "外部根因。"
                )
            ),
        ]
    )

    result = DataCopilotAgent(registry, dataset_id, client).ask(
        "为什么 3 月 completed 订单销售额下降？"
    )

    assert result.tool_calls_used == 1
    assert result.tool_calls_used <= 5
    assert len(arguments["metrics"]) == 3
    assert "不能确认外部根因" in result.answer


def test_existing_conversation_evidence_is_reused_without_another_tool_call(
    orders_dataset: tuple[DatasetRegistry, str],
) -> None:
    registry, dataset_id = orders_dataset
    client = FakeLLMClient(
        [
            _tool_call(
                "aggregate_dataset",
                {
                    "dimensions": [
                        {
                            "name": "month",
                            "column": "created_at",
                            "time_grain": "month",
                        }
                    ],
                    "metrics": [
                        {
                            "name": "completed_amount",
                            "function": "sum",
                            "column": "amount",
                        }
                    ],
                    "filters": [
                        {
                            "column": "status",
                            "operator": "eq",
                            "value": "completed",
                        }
                    ],
                    "order_by": [{"field": "month", "direction": "asc"}],
                    "limit": 12,
                },
            ),
            LLMResponse(
                text="1 月和 2 月均为 1050，3 月为 520，4 月为 1050。"
            ),
            LLMResponse(text="基于已有 Evidence，最低的是 3 月，为 520。"),
        ]
    )
    agent = DataCopilotAgent(registry, dataset_id, client)

    first = agent.ask("按月汇总 completed amount。")
    second = agent.ask("其中哪个月最低？")

    assert first.tool_calls_used == 1
    assert second.tool_calls_used == 0
    assert second.rounds == 1
    assert sum(message.role.value == "tool" for message in agent.messages) == 1


def test_unsupported_mutation_safety_behavior_remains_unchanged(
    orders_dataset: tuple[DatasetRegistry, str],
) -> None:
    registry, dataset_id = orders_dataset
    client = FakeLLMClient(
        [
            LLMResponse(
                text=(
                    "我不能修改数据；当前能力仅支持对已注册数据集进行"
                    "只读分析。"
                )
            )
        ]
    )

    result = DataCopilotAgent(registry, dataset_id, client).ask(
        "把所有 amount 小于 0 的记录改成 0。"
    )

    assert result.tool_calls_used == 0
    assert "不能修改" in result.answer
    assert "UPDATE" not in result.answer
