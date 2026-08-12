## 1. Project Mission

Data Copilot 的目标是构建一个：

> 面向数据分析、SQL / 数据库查询和数据工程排障的通用智能数据助手。

它应该帮助用户完成从：

```text
发现数据问题
↓
分析现象
↓
查询数据
↓
验证假设
↓
排查链路
↓
形成 Evidence
↓
输出结论
```

的一整套数据问题解决流程。

---

## 2. Product Scope

### Core Domains

```text
Data Analysis
SQL / Database
Data Engineering Troubleshooting
```

### Primary Data Types

第一阶段：

```text
CSV
Parquet
JSON / JSONL
Database Tables
Structured Logs
Text Corpus
```

以后再考虑：

```text
Streaming
Data Warehouse
Airflow
Spark
Cloud Data Platform
```

---

## 3. Target Users

主要面向：

```text
Data Analyst
Data Engineer
Analytics Engineer
Data Scientist
Backend / BI Developer
学习数据相关技术的开发者
```

---

## 4. Typical User Questions

### Analysis

```text
为什么销售额下降？
哪个用户群变化最大？
这个数据集中有哪些明显异常？
```

### SQL / Database

```text
这张表是什么结构？
这几个表怎么关联？
帮我计算过去 30 天 GMV。
为什么这条 SQL 结果不对？
```

### Troubleshooting

```text
为什么今天数据少了？
哪个上游任务导致这个指标异常？
数据从什么时候开始延迟？
```

---

## 5. Architecture Principles

### Principle 1

> LLM 负责智能，程序负责可靠性。

### Principle 2

> The LLM reasons about data; the data engine processes data.

### Principle 3

> Compute where the data lives.

### Principle 4

> Raw Big Data must not be placed directly into the LLM context.

### Principle 5

> Evidence before conclusion.

### Principle 6

> Read-only by default.

### Principle 7

> Explicit Permission > Implicit Trust.

---

## 6. Architecture

```text
                       User
                         │
                         ▼
                    Data Copilot
                         │
                         ▼
                      Planner
                         │
         ┌───────────────┼────────────────┐
         │               │                │
         ▼               ▼                ▼
      Metadata        Knowledge        Data Query
         │               │                │
  Schema / Profile      RAG        Execution Layer
         │               │                │
         │               │      ┌─────────┼─────────┐
         │               │      │         │         │
         │               │   DuckDB      SQL      Spark
         │               │
         └───────────────┼────────────────┘
                         │
                         ▼
                  Compact Evidence
                         │
                         ▼
                        LLM
                         │
                         ▼
                Insight / Root Cause
```

---

## 7. Three Logical Layers

### Intelligence Layer

负责：

```text
User Intent
Planning
Hypothesis Generation
Tool Selection
Interpretation
Final Answer
```

主要组件：

```text
LLM
Planner
Skills
Agent Loop
```

### Semantic Layer

负责：

```text
Schema
Dataset Profile
Metric Definition
Business Semantics
Data Dictionary
RAG
Domain Context
```

### Execution Layer

负责：

```text
Scanning
Filtering
Aggregation
SQL
Sampling
Profiling
Data Quality
Log Query
```

可能包含：

```text
Pandas
DuckDB
Database
Spark
```

---

## 8. Data Execution Backend

长期接口方向：

```text
DataExecutionBackend
│
├── PandasBackend
├── DuckDBBackend
├── SQLBackend
└── SparkBackend
```

Agent 不应该依赖某个具体 Backend。

Backend selection 应由程序结合：

```text
Source Type
File Size
Columns
Format
Memory
Query Type
Available Engine
```

决定。

---

## 9. Dataset Understanding

禁止：

```text
read all rows
→ stringify
→ LLM
```

正确方式：

```text
Data
↓
Dataset Profile
↓
Representative Samples
↓
Aggregates
↓
LLM
```

Profile 应逐步支持：

```text
Schema
Rows
Columns
Types
Null Rate
Distinct Count
Min / Max
Mean / Median
Quantiles
Top Values
Time Range
Potential Keys
Samples
```

---

## 10. Data Query Strategy

对大型数据：

```text
LLM
↓
提出分析问题
↓
Data Tool
↓
执行计算
↓
Compact Result
↓
LLM
```

例如：

```text
100M rows
↓
GROUP BY
↓
10 rows
↓
LLM
```

---

## 11. Sampling Strategy

支持：

```text
Random
Stratified
Time-based
Outlier
Error-oriented
```

Sampling 必须：

```text
有目的
有上限
可解释
```

---

## 12. Structured Data vs RAG

### Structured Data

优先：

```text
SQL
Aggregation
Filtering
Statistics
```

### Knowledge Documents

优先：

```text
RAG
```

包括：

```text
Metric Definitions
Data Dictionary
Pipeline Docs
Business Docs
SOP
Schema Docs
```

### Text Corpus

如果问题是语义搜索：

```text
Embedding / RAG
```

可以作为 Execution Strategy。

---

## 13. Semantic Layer

Agent 应支持可插拔领域语义。

例如：

```text
E-commerce Context
Game Context
AI Corpus Context
```

这些 Context 不改变：

```text
Core Agent
Execution Engine
```

只改变：

```text
Metric Meaning
Domain Knowledge
Analysis Guidance
```

---

## 14. Tool Design

Tool 的原则：

```text
Small
Explicit
Deterministic
Bounded
Observable
Testable
```

不要创建：

```text
do_everything_with_data()
```

而应该逐渐形成类似：

```text
inspect_source
profile_dataset
sample_rows
aggregate
filter
list_tables
describe_table
execute_readonly_sql
explain_query
check_freshness
compare_row_counts
read_job_log
```

实际名称以实现为准。

---

## 15. Database Safety

第一版仅支持：

```text
SELECT
WITH ... SELECT
EXPLAIN
Metadata Query
```

禁止：

```text
INSERT
UPDATE
DELETE
DROP
ALTER
TRUNCATE
CREATE
GRANT
REVOKE
```

同时设置：

```text
Query Timeout
Row Limit
Result Size Limit
Connection Allowlist
```

---

## 16. Result Policy

LLM 不应该接收无限结果。

所有 Tool 必须有：

```text
Row Limit
Byte Limit
Timeout
Truncation Policy
```

返回：

```text
Compact Evidence
```

而不是 Raw Dump。

---

## 17. Evidence Model

最终答案尽量区分：

```text
Observation
Evidence
Inference
Conclusion
Uncertainty
```

例如：

```text
Observation:
Android DAU decreased by 38%.

Evidence:
query X, result Y.

Inference:
The decrease correlates with missing Android events.

Root Cause:
Only after pipeline evidence confirms it.
```

Agent 不应把推测包装成事实。

---

## 18. Logging

继续记录：

```text
run_id
task
tool_call
tool_result summary
round
latency
error
status
```

未来扩展：

```text
token_usage
estimated_cost
data_source
query_count
rows_scanned
user_rating
```

禁止日志泄露：

```text
Password
API Key
DB Secret
Full Sensitive Dataset
```

---

## 19. Evaluation

至少建立以下指标：

```text
Task Success Rate
SQL Correctness
Analysis Correctness
Root Cause Accuracy
Evidence Accuracy
No-answer Accuracy
Tool Call Count
Rounds
Latency
Token Cost
Safety Violation
```

测试体系：

```text
Unit Test
Integration Test
Synthetic Dataset Test
Golden SQL Test
A/B Agent Test
Real-world Repository/Data Test
Human Evaluation
```

---

## 20. Development Workflow

每个开发阶段都必须经历：

```text
Problem
↓
Scope
↓
Non-goals
↓
Architecture
↓
Implementation
↓
Unit Test
↓
Integration Test
↓
Manual Test
↓
Evaluation
↓
Documentation
↓
Seal
```

---

## 21. Phase Strategy

### Phase 1 — Local Data Foundation

目标：

```text
CSV / Parquet
↓
Inspect
↓
Profile
↓
Sample
↓
Aggregate
↓
LLM Explanation
```

优先让 Data Copilot 真正能够理解一个本地数据集。

### Phase 2 — Data Analysis Agent

加入：

```text
filter
group
trend
distribution
data quality
basic anomaly analysis
```

### Phase 3 — SQL / Database

加入：

```text
Database Metadata
Schema
Read-only SQL
Explain
Query Evidence
```

### Phase 4 — Semantic Layer

加入：

```text
Metric Definition
Data Dictionary
RAG
Domain Context
```

### Phase 5 — Data Quality

加入：

```text
Freshness
Completeness
Uniqueness
Null
Duplicate
Row Count Drift
```

### Phase 6 — Troubleshooting

加入：

```text
Pipeline Metadata
Logs
Dependency
Failure Analysis
Root Cause Workflow
```

### Phase 7 — Real Integrations

再考虑：

```text
PostgreSQL
MySQL
Airflow
Spark
GitHub
Warehouse
MCP Servers
```

具体顺序必须由真实使用需求决定。

---

## 22. Explicit Non-goals

现阶段不做：

```text
Production Auto-remediation
Arbitrary Shell
Database Write
Automatic Data Modification
Multi-Agent Architecture
Full BI Platform
Notebook Replacement
Data Warehouse Replacement
Universal ETL Platform
```

---

## 23. Relationship to code-agent-cli

`code-agent-cli`：

```text
Agent Architecture Learning Project
```

Data Copilot：

```text
Data Product
```

可以复用：

```text
Agent Loop
ToolRegistry
Planning
Skills
Memory
RAG
MCP
Logging
Safety Design
```

但每次复用前必须问：

> 这个抽象是否真的适合 Data Copilot？

不要为了“复用代码”而制造错误架构。

---

## 24. Definition of Useful

一个功能只有满足下面条件才算有价值：

```text
用户确实存在这个问题
+
Agent 能比纯聊天模型做得更可靠
+
结果有 Evidence
+
过程可测试
+
失败时能安全停止
```

---

## 25. Core Product Question

开发过程中持续问：

> 用户现在遇到了什么数据问题？

不要问：

> 我还能给 Agent 加什么技术？

正确顺序：

```text
User Problem
↓
Required Evidence
↓
Required Capability
↓
Tool / Retrieval / Workflow
↓
Implementation
```

---

## 26. Current Starting Point

Data Copilot 的第一开发目标不是：

```text
支持所有数据库
```

而是：

> 让 Agent 能可靠、安全、可验证地理解和分析一个本地结构化数据集。

第一条完整 Vertical Slice：

```text
User
↓
提供 CSV / Parquet
↓
Data Copilot Inspect
↓
Profile
↓
User Question
↓
Planner
↓
Data Tool
↓
Compact Evidence
↓
LLM
↓
Grounded Answer
```

只有这条链路稳定后，才进入下一阶段。

---

## 27. Phase 1.5 Agent Boundary

Phase 1.5 的最小 Intelligence Layer 固定为：

```text
User Question
↓
LLM Client
↓
Static Six-Tool Dispatcher
↓
Existing Typed Data Tool
↓
Compact Evidence
↓
LLM Final Answer
```

当前 Agent 只绑定一个已显式注册的 Dataset。Dataset ID 由程序持有，不是
LLM Tool 参数。Tool Dispatcher 是静态 capability allowlist，不做动态发现、
插件加载或权限推断。

LLM 返回的 Tool arguments 始终是不可信输入，必须经过 typed parsing 和既有
Execution Layer 的列、语义与资源限制校验。成功 Tool Result 只能通过
EvidenceBuilder / EvidenceFormatter 进入 LLM context；raw result、path 和内部
SQL 不得旁路 Evidence Layer。

每个问题最多执行五个 Tool Calls。达到限制是明确失败，不是成功。Conversation
只存在于当前进程，不包含 persistent memory、planner、RAG 或 MCP。

---

## 28. Phase 1.5 LLM Provider Boundary

`LLMClient` 是 Agent 唯一依赖的 provider-neutral 接口。当前只允许两个显式
adapter：OpenAI 使用 Responses API；DeepSeek 使用其 OpenAI-compatible Chat
Completions API。Provider 由 `DATA_COPILOT_PROVIDER` 确定性选择，不做 discovery、
fallback、routing 或自动切换。

应用只在 CLI bootstrap 边界加载一次 `.env`，并使用 `override=False` 保证已有
系统环境变量优先。Provider、model 和所选 provider 的 API key 必须显式存在；
未知或不完整配置 fail closed。API key 不进入 Prompt、Evidence、Tool arguments
或日志。

两个 adapter 共享现有 typed conversation 和六 Tool schemas，但 provider-specific
message mapping 保持在各自 adapter 内。Agent、ToolDispatcher、Evidence Layer 和
`MAX_TOOL_ROUNDS = 5` 不因 provider 改变。

---

## 29. Phase 1.6 Evaluation Boundary

Phase 1.6 的评测链路固定为：

```text
Typed Eval Case
→ Existing DataCopilotAgent
→ Six Safe Data Tools
→ Compact Evidence
→ Final Answer
→ Deterministic Checks + Human Review Flag
→ Structured Eval Result
```

Mock eval 使用 `FakeLLMClient`，可在 CI 中确定性运行。Live eval 必须通过显式
CLI mode 启动，记录 provider、model、latency、Tool calls、rounds 和 provider
可用时的 token usage；普通 pytest 不得访问付费 API。

自然语言评分不采用另一个 LLM 作为唯一 judge。第一版只自动检查 required facts、
forbidden claims、Tool selection 和 deterministic safety constraints，并明确标记
需要人工 grounding review 的 case。Generated results 不包含 API key、resolved
path、raw dataset 或内部 SQL。

Task Success、Tool Selection、Answer Accuracy、Grounding、No-answer、Safety 和
Efficiency 是独立指标。正确且 grounded 的答案不会仅因多余的只读 Tool 调用而被
判为 Task Failure；该问题必须反映在 Tool Selection / Efficiency 指标中。运行失败、
答案缺失、unsupported claim 或 forbidden capability 仍可导致 Task Failure。

Eval infrastructure 只测量现有能力，不注册 Tool、不改变 Evidence channel，也不为
特定 case 修改 System Prompt。Safety deterministic cases 的目标是 100%；其他
live 指标首先作为真实 baseline，失败必须记录而不是 overfit。

---

## 30. Phase 2.1 PostgreSQL Connection Boundary

Phase 2.1 只建立 PostgreSQL 的安全注册与连接基础：

```text
.env / environment
→ validated PostgresConnectionConfig
→ in-memory DatabaseRegistry
→ opaque database_id
→ PostgresEngine.ping(database_id)
```

`DatabaseRegistry` 与 Phase 1 的 `DatasetRegistry` 分离。内部 `Database` 保存 DSN、
database name 和 connect timeout；public metadata 只包含 opaque ID、database type
和 display name。凭据不得进入 Agent、Prompt、Evidence、Eval result 或 public error。
Registry 对完全等价的 configuration 做进程内去重，不持久化。

`PostgresEngine` 当前唯一 capability 是 `ping(database_id)`。它用 psycopg 3 建立
同步连接，应用 1–60 秒的集中 connect timeout，在执行程序写死的 `SELECT 1` 前将
session transaction mode 设为 read-only。read-only 设置或 health check 的任何失败
都 fail closed，并转换为不包含 driver details 或 DSN 的 domain error。

本阶段不提供 schema discovery、SQL generation、SQL parsing、任意 SQL execution、
EXPLAIN、database Tool、CLI workflow 或 connection pooling。这些能力不能通过
`PostgresEngine` 的当前接口获得。
