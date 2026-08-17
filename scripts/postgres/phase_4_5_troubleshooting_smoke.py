"""Focused real PostgreSQL collection-to-Agent troubleshooting smoke."""

import json

from data_copilot import DatabaseCopilotAgent
from data_copilot.config import read_postgres_config
from data_copilot.databases import DatabaseRegistry
from data_copilot.diagnostics import (
    PostgresDiagnosticCollector,
    TroubleshootingResources,
)
from data_copilot.llm import FakeLLMClient, LLMResponse, LLMToolCall


def main() -> int:
    config = read_postgres_config()
    if config.database_name != "data_copilot_test":
        print(
            "troubleshooting safety=failed expected_database=data_copilot_test; "
            "no collection was executed"
        )
        return 1
    registry = DatabaseRegistry()
    database = registry.register(config, display_name="Phase 4.5 Local Fixture")
    collector = PostgresDiagnosticCollector(registry)
    before = collector.collect(
        database.database_id,
        schema_name="commerce",
        table_name="orders",
    )
    after = collector.collect(
        database.database_id,
        schema_name="commerce",
        table_name="orders",
    )
    before_snapshot = before.snapshot.model_copy(
        update={"snapshot_id": "real_smoke_before"}
    )
    after_snapshot = after.snapshot.model_copy(
        update={"snapshot_id": "real_smoke_after"}
    )
    client = FakeLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    LLMToolCall(
                        call_id="compare_real_snapshots",
                        name="compare_table_snapshots",
                        arguments=json.dumps(
                            {
                                "before_snapshot_id": "real_smoke_before",
                                "after_snapshot_id": "real_smoke_after",
                            }
                        ),
                    ),
                )
            ),
            LLMResponse(
                text=(
                    "Observed fact: the two transactionally collected snapshots "
                    "contain no drift findings."
                )
            ),
        ]
    )
    agent = DatabaseCopilotAgent(
        registry,
        database.database_id,
        client,
        troubleshooting_resources=TroubleshootingResources(
            snapshots=(before_snapshot, after_snapshot)
        ),
    )
    result = agent.ask("Compare the two approved current diagnostic snapshots.")
    tool_contents = tuple(
        message.content or ""
        for message in agent.messages
        if message.tool_call_id == "compare_real_snapshots"
    )
    checks = {
        "typed_snapshots": before_snapshot.row_count == 1200
        and after_snapshot.row_count == 1200,
        "diagnostic_evidence": len(tool_contents) == 1
        and tool_contents[0].startswith("DIAGNOSTIC_EVIDENCE\n"),
        "agent_consumption": result.tool_calls_used == 1
        and result.rounds == 2
        and "no drift findings" in result.answer,
        "bounded_output": len(tool_contents[0]) <= 16_000 if tool_contents else False,
        "secret_isolation": all(
            value not in tool_contents[0]
            for value in (config.dsn, "postgresql://")
        ) if tool_contents else False,
    }
    for name, passed in checks.items():
        print(f"troubleshooting {name}={'passed' if passed else 'failed'}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
