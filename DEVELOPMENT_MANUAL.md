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

### Phase 3 — Semantic Layer + RAG ✅ COMPLETE

加入：

```text
Semantic Catalog
Semantic Resolution and Evidence
Business-document RAG
Semantic Agent Integration
Semantic + RAG Evaluation and Closure
```

### Phase 4 — Not started

Scope requires separate approval. Phase 3 closure does not start or predefine
Phase 4 functionality.

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

---

## 31. Phase 2.2 PostgreSQL Metadata Boundary

Phase 2.2 在 Phase 2.1 的 registry 和 opaque `database_id` 边界上增加三个明确的
program-side capability：

```text
list_tables(database_id, optional schema)
inspect_table(database_id, schema_name, table_name)
get_relationships(database_id, schema_name, table_name)
```

这三个 capability 仍属于 Execution / Metadata boundary，尚未注册为 Agent Tool，
也不进入 Evidence。PostgreSQL table identity 必须始终使用 `schema_name + table_name`，
schema 和 table lookup 值使用参数绑定，不拼接 identifier。

Metadata SQL 是固定的 program-owned `pg_catalog` query。每次 operation 单独建立连接，
在第一条 query 前设置 read-only；设置失败必须 fail closed。Public typed result 只包含
relation type、column type/nullability、声明的 primary key、foreign key、basic index，
以及相对目标 table 的 inbound/outbound relationship。不得推断 potential key 或业务关系。

所有结果均有确定性上限：200 tables、200 columns、200 relationships 和 100 indexes。
Query 在适用处额外读取一条记录判断 truncation，结果通过 `truncated` 和 warnings 明确
报告截断。System schema 默认排除。

本阶段仍不允许 caller/LLM SQL、通用 SQL executor、SQL AST validator、EXPLAIN、
database Agent Tool、database Evidence、schema inference、MySQL 或 connection pool。

---

## 32. Phase 2.3 Read-only SQL Validation Boundary

Phase 2.3 新增一个独立、无数据库连接的 validation pipeline：

```text
untrusted SQL text
→ sqlglot PostgreSQL parser
→ exactly-one-statement check
→ whole-tree read-only policy
→ ValidatedSQL
```

`SQLValidator.validate(sql)` 只允许 SELECT、read-only set operation、
`WITH ... SELECT` 和 plain `EXPLAIN SELECT`。Validator 遍历整棵 AST；DDL、DML、
administrative nodes 即使出现在 writable CTE 或其他 nested position 也必须拒绝。
`SELECT INTO`、所有 row-locking clause、`EXPLAIN ANALYZE` 和第一版所有 parenthesized
EXPLAIN options 均 fail closed。

危险函数采用小型明确 denylist，包括 PostgreSQL file/large-object、`dblink*`、sequence
mutation、advisory lock、backend control、WAL/control、logical message 和 sleep 等明显
有副作用或资源风险的 capability。此 denylist 不声称穷举 extension 或 user-defined
volatile function；Phase 2.4 的 read-only session、数据库 read-only credential、timeout、
result limit 将作为 defense-in-depth，而不是由 AST validator 单独承担全部安全保证。

`ValidatedSQL` 只保存 original SQL、normalized PostgreSQL SQL、statement type 和
`is_explain`。它不保存 database ID、credential 或 execution result。Phase 2.3 不修改
PostgresEngine，不提供 execution、rewriting、automatic LIMIT、Agent Tool、Evidence、
EXPLAIN execution、SQL debugging 或 MySQL dialect。

---

## 33. Phase 2.4 PostgreSQL Agent and Read Execution Boundary

Phase 2.4 增加独立的 single-database Agent path，不改变 Phase 1 dataset Agent：

```text
Natural-language question
→ static four-tool Database Dispatcher
→ metadata and/or LLM-generated PostgreSQL
→ mandatory SQLValidator
→ reject EXPLAIN
→ opaque database_id resolution
→ per-query read-only connection + statement timeout
→ bounded typed result
→ shared Compact Evidence
→ grounded answer
```

LLM 只看到 `list_tables`、`inspect_table`、`get_relationships` 和
`execute_read_query`。`database_id` 由程序绑定，Tool schema 不允许选择 ID、DSN 或
credential。Validator 不能成为 LLM Tool，也没有未验证的 execution bypass。

`execute_read_query` 必须先验证，再连接。每次 query 都重新设置 read-only，并通过
program-owned `pg_catalog.set_config(..., is_local=true)` 应用 statement timeout。
结果最多 50 columns；超过时在 fetch 前失败。最多 fetch 201 rows 并返回 200 rows，
显式记录 source truncation。Query 使用 program-named server-side cursor，避免 client
cursor 预先缓冲完整结果。SQL 不做 automatic LIMIT rewriting。

Database query result 与 metadata Tool result 复用现有 EvidenceBuilder、cell normalization、
total-size enforcement 和 `DATA_EVIDENCE` formatter。Evidence source identity 恰好是
dataset ID 或 database ID 之一。Source truncation 与 Evidence truncation 继续分离。
SQL text、credential、connection config、raw driver error 和 stack trace 不进入 Evidence。

本阶段不提供 EXPLAIN execution、performance debugging、automatic repair、planner、
Semantic Layer、RAG、MySQL、write/DDL、cross-database、pooling 或 multi-database Agent。

---

## 34. Phase 2.5 SQL Explain and Debug Boundary

Phase 2.5 在冻结的 read-query pipeline 上增加第五个 database Agent Tool：
`explain_query`。调用方只传 underlying read-only query；程序必须先经过原有
`SQLValidator`，明确拒绝用户提供的 EXPLAIN，再构造固定的
`EXPLAIN (FORMAT JSON) <normalized query>`。每次操作仍独立解析 opaque
`database_id`、建立 read-only connection，并应用 transaction-local statement timeout。
`EXPLAIN ANALYZE` 永远不构造，因此 underlying query 不执行。

PostgreSQL JSON plan 不直接进入 Evidence。程序只保留 node type、relation/alias、join
type、startup/total cost、estimated rows/width、filter、index name 和 child structure，
并应用 `MAX_PLAN_NODES=100`、`MAX_PLAN_DEPTH=20`。截断必须同时出现在 typed result、
warning 和 Evidence provenance。Raw plan、SQL、driver diagnostics、credential 和 connection
configuration 不得进入 Agent context 或默认日志。

Database Agent 可以直接解释纯 SQL syntax，不要求 Tool。Performance question 使用
`explain_query`；schema/error/JOIN debugging 可按需组合 metadata 和 bounded read query
Evidence。Plan node 是 observable fact，不等于 confirmed performance cause。Suggested SQL
必须标为未验证，除非它确实通过 `execute_read_query` 成功执行。本阶段不提供
EXPLAIN ANALYZE、automatic repair/rewrite、index recommendation engine、database mutation、
DBA maintenance、MySQL、RAG 或 Semantic Layer。

---

## 35. Phase 2.6 Real PostgreSQL and Evaluation Closure

Phase 2.6 不新增 Agent capability，只验证 Phase 2 的完整链路。2026-08-12 在 Apple
Silicon macOS 上通过 Homebrew PostgreSQL 18.4 建立独立 `data_copilot_test` fixture 和
`data_copilot_ro` role。Role 只获得 LOGIN、CONNECT、schema USAGE、table SELECT，且
role-level `default_transaction_read_only=on`；它不是 SUPERUSER，也没有 CREATEDB、
CREATEROLE、INHERIT 或 schema creation privilege。程序的 per-operation read-only mode、
SQLValidator 和 statement timeout 仍作为独立 defense-in-depth。

Real smoke 覆盖 registry、ping、metadata、PK/FK/index/relationship、read query、aggregate、
200-row truncation、program-owned EXPLAIN 和 validator pre-connection rejection。使用相同
application role 的 INSERT、UPDATE、DELETE、CREATE、DROP、ALTER 均由 PostgreSQL
`ReadOnlySqlTransaction` 阻止。Fixture/eval 后 row counts 保持不变。真实环境同时发现
Phase 2.2 `LIST_TABLES_SQL` 的 psycopg placeholder defect：optional NULL 缺少显式 text
context，LIKE literal 的 `%` 未转义；修复保持 program-owned SQL 与 parameter binding。

Eval infrastructure 继续复用原有 metrics/result/persistence contract，并增加独立
`DatabaseEvalRunner`；case source 必须恰好为 dataset 或 database。Database runner 只绑定
program-owned database ID，不新增 Tool。12-case one-shot DeepSeek eval（model
`deepseek-v4-flash`）结果为：8/12 task success、100% tool selection、66.7% answer check、
100% grounding check、0% no-answer、100% safety、83.3% efficiency，平均 2.83 Tool calls、
2.25 rounds、5513.40 ms，provider usage 63,982 tokens。

人工 review 认为 JOIN multiplication 和 EXPLAIN 两项是 deterministic phrase scoring
false negative：answers 本身 grounded 且有合理限定；原始自动分数仍保留不改写。真正的
product failures 是 region aggregate 与 missing-concept/no-answer 达到 5-call round limit，
没有 final answer。由于 no-answer 仍为 0%，Phase 2 暂不建议 closure，也不得开始 Phase 3。
后续需要独立批准的收口工作应聚焦 tool economy/stop behavior 和 semantic scoring，而不是
扩展 SQL/database capability 或针对 fixture 过拟合 prompt。

---

## 36. Phase 3.1 Semantic Catalog Foundation

Phase 1 和 Phase 2 已冻结。Phase 3.1 只建立独立的、程序管理的 Semantic Catalog：

```text
explicit trusted local YAML
→ safe bounded parsing
→ strict typed definitions
→ deterministic validation
→ in-memory SemanticCatalog
```

受支持的定义只有 `MetricDefinition`、`DimensionDefinition` 和 `GlossaryTerm`。Metric
只描述业务含义和 `schema.table.column` 数据输入，不包含 SQL、formula executor 或 metric
compiler。Dimension 记录业务维度和 source fields，但不查询数据库发现 values。Glossary
可通过稳定 ID 引用 metric 和 dimension。

每个 YAML source 必须声明 version、definition type 和 definitions。Loader 只读取显式文件，
或对显式目录做有数量和文件大小限制的单层扫描；不递归扫描，不接受 symlink，不连接
PostgreSQL，也不调用 LLM。PyYAML `safe_load` 之后必须经过 Pydantic strict models，unknown
fields fail closed，因此 YAML 不能加入 arbitrary SQL 或覆盖 program-managed provenance。

Catalog lookup 只支持 stable ID、canonical name 和 explicit synonym。Normalization 仅做
trim + case-insensitive comparison；不做 fuzzy match、embedding 或 LLM classification。
duplicate ID、duplicate canonical name、ambiguous synonym 和 invalid glossary reference 均在
catalog construction 时失败。Provenance 只暴露 source file name + definition ID，不暴露
absolute filesystem path。

本阶段不把 catalog 写入 System Prompt，不向 Agent 注册 Semantic Tool，也不提供 RAG、
semantic ranking、live database cross-check 或 metric-to-SQL。后续阶段只能按需把 compact
relevant semantic evidence 接入 Agent，并继续让生成 SQL 经过冻结的 Phase 2 SQLValidator。

---

## 37. Phase 3.2 Semantic Resolution + Semantic Evidence

Phase 3.2 在冻结的 Semantic Catalog 上增加 LLM-free resolution boundary：

```text
bounded extracted candidate terms
→ exact ID / canonical name / explicit synonym resolution
→ typed SemanticResolution
→ catalog identity re-validation
→ bounded SEMANTIC_EVIDENCE
```

`SemanticResolver` 不解析自然语言，只接收 caller 已提取的 candidate terms。它在 metric、
dimension 和 glossary 三种类型中统一检查 conservative normalized aliases。一个 term 匹配
多个类型时必须抛出 ambiguity error；不得按 type、insertion order、shortest name 或其他
隐含优先级选择。Multi-term resolution 最多 20 项并保持输入顺序。

Resolution result 只记录 query term、semantic type、stable definition ID、canonical name、
match type 和 safe provenance，不复制完整 definition。`SemanticEvidenceBuilder` 必须使用
stable type + ID 从相同 catalog 重新取得 definition，并验证 canonical name 和 provenance，
因此 forged、stale 或 unknown resolution 不能进入 evidence。

`SEMANTIC_EVIDENCE` 使用独立的 typed envelope 和 deterministic compact JSON formatter，只
包含相关 definition。它分别限制 definition count、text chars、synonyms、field references
和 serialized chars；任何裁剪必须设置 `truncated` 并提供 warning。Total-size reduction 只
删除完整的 trailing definitions，不切断 JSON。Provenance 继续只包含 logical source name
和 definition ID。

语义与观测证据必须保持独立：

```text
SEMANTIC_EVIDENCE = trusted configured business meaning
DATA_EVIDENCE     = observed data/query facts
```

即使 business definition 含有 prompt-like 或 SQL-like text，也只是 content，不能变成 system
instruction、Tool permission 或 executable SQL。本阶段不修改 Agent prompt，不注册 Agent
Tool，不调用 LLM/PostgreSQL，不生成 SQL，也不开始 RAG、embedding、fuzzy search、live
catalog consistency check 或 Phase 3 eval。

---

## 38. Phase 3.3 Minimal Business-document RAG

Phase 3.3 在冻结的 structured Semantic Catalog 之外增加独立的 trusted document retrieval
boundary：

```text
explicit local Markdown / text
→ bounded path-safe loading
→ deterministic heading / paragraph chunking
→ bounded in-memory BM25-style lexical index
→ top-k retrieval
→ bounded DOCUMENT_EVIDENCE
```

`BusinessDocumentLoader` 只接受显式文件、显式文件列表或显式 non-recursive directory。
支持 `.md`、`.markdown` 和 `.txt`；拒绝 symlink component、invalid UTF-8、empty document、
duplicate logical source 以及 file count/bytes/chars limit。Public `BusinessDocument` 只保留
content-derived stable ID、title、logical filename 和 program-managed content，不暴露 path。

`BusinessDocumentChunker` 对 Markdown 使用 heading sections，对 plain text 使用 paragraphs，
再以 character bound 做 deterministic split。每个 `DocumentChunk` 保留 content-derived
chunk ID、document ID、title、heading、logical source、ordinal 和一致的 safe provenance。
Document/chunk/collection limits 都由程序强制执行。

`BusinessDocumentIndex` 是 startup-rebuildable in-memory local index，不持久化，也不连接
external service。V1 使用 standard-library Unicode tokenization 和 BM25-style scoring；query、
top_k 和 index chunks 有明确上限。只返回 positive lexical matches；相同 score 按 logical
source、ordinal、chunk ID 稳定排序，不使用 embedding、fuzzy match、LLM rewrite 或 reranker。

`DOCUMENT_EVIDENCE` 只包含 retrieved chunks，并限制 chunk count、chunk text、citation
metadata 和 total serialized JSON chars。裁剪必须设置 `truncated` 和 warnings；total-size
reduction 删除完整 trailing chunks，不切断 JSON。Citation foundation 只使用 document title、
heading、logical source、ordinal、document/chunk IDs，不虚构 Markdown/text page number。

三个 evidence channel 保持不同职责：

```text
SEMANTIC_EVIDENCE = authoritative structured business definitions
DOCUMENT_EVIDENCE = retrieved explanatory business-document context
DATA_EVIDENCE     = observed data/query facts
```

Document 是 trusted knowledge source，但 content 不是 control instruction。Prompt-like 或
SQL-like text 只能原样成为 evidence content，不得执行、修改 Tool permission 或覆盖 system
rules。本阶段不修改 Agent/Prompt，不注册 RAG Tool，不生成或执行 SQL，不调用 LLM、
PostgreSQL、network 或 external API，也不提供 vector DB、embedding、PDF/DOCX、catalog
conflict resolution、Phase 3 live eval 或 Phase 3.4 capability。

---

## 39. Phase 3.4 Semantic Agent Integration

Phase 3.4 扩展 existing single `DatabaseCopilotAgent`，不创建 multi-agent，也不修改 frozen
Phase 2 database dispatcher、SQL validator 或 execution engine。Agent 的 five database Tools
保持原样；只有显式配置 `SemanticCatalog` 和/或 `BusinessDocumentIndex` 时，才分别追加：

```text
resolve_semantic   → bounded SEMANTIC_EVIDENCE
retrieve_documents → bounded DOCUMENT_EVIDENCE
```

两个 adapter 只接受 strict bounded arguments。`resolve_semantic` 接收 caller/LLM 提取的
candidate terms，复用 deterministic exact ID/name/synonym resolution 和 existing semantic
evidence builder；missing/ambiguity 通过 safe structured Tool error 返回，不选择任一 meaning。
`retrieve_documents` 只接受 lexical query + bounded top_k，复用 configured local index 和
existing document evidence builder。Tool schema 不暴露 catalog、raw documents、path、index
internals、database ID、credential 或 SQL validator。

Agent routing 是 need-based，不强制 semantic → document → metadata → query chain：

```text
plain row count       → database Tool only
metric definition     → resolve_semantic
policy / rationale    → semantic + document as needed
business metric value → semantic + metadata verification + read query
```

所有 optional context Tool calls 与 database Tool calls 共用原有 `MAX_TOOL_ROUNDS=5`，不增加
budget。Conversation 继续保留 accumulated Evidence，prompt 要求不重复 equivalent resolution、
retrieval 或 metadata probe。Budget exhaustion 仍进入 Tool-disabled final synthesis；该 synthesis
可以使用 accumulated SEMANTIC、DOCUMENT、DATA Evidence，但 required numerical DATA Evidence
缺失时仍必须 no-answer。

三个 channel 的 ownership 不合并：structured semantic definition 是 current canonical business
meaning；document evidence 是 explanation/history/context；data evidence 是 observed database
fact。Document 与 catalog material conflict 时只 disclosure，不自动 merge。Citation 只能使用
Evidence 中的 logical provenance，不得创造 path 或 source。

Semantic definition 只给 LLM 提供 meaning、required fields 和 filters，不生成 executable SQL。
Agent 在需要时使用 metadata 验证 semantic field；缺失时报告 semantic/database inconsistency，
不得生成 fabricated field SQL。LLM-generated SQL 继续进入完全相同的：

```text
SQLValidator
→ registered database ID
→ read-only PostgreSQL operation + timeout
→ bounded DATA_EVIDENCE
```

SEMANTIC_EVIDENCE、DOCUMENT_EVIDENCE 和 DATA_EVIDENCE 全部是 content，不是 instruction 或
permission。Prompt-like/SQL-like text 不得触发 Tool。Optional resources 未配置时，Agent schema
和 Phase 2 behavior 保持 five-tool compatible。Domain knowledge 只来自 generic catalog/document
configuration，不硬编码行业规则。本阶段不提供 metric compiler、embedding、vector DB、
reranker、automatic conflict resolver、multi-agent、MySQL、write 或 Phase 3.5 live eval；Phase 3
在 3.5 完成前不宣告 closure。

---

## 40. Phase 3.5 Semantic + RAG Live Eval and Closure

Phase 3.5 不增加 Agent capability，只验证 Phase 3.1–3.4 已有架构。评测使用显式 synthetic
SemanticCatalog、local business-document index、restricted PostgreSQL fixture 和同一个
`DatabaseCopilotAgent`。Eval result 在既有 Tool trace 之外记录实际出现的 semantic、document、
data Evidence channel，并分别计算 Semantic Grounding、Document Grounding 和 Data Grounding；
旧的 forbidden-claim Grounding 继续保留，但不能替代 source-specific 指标。

付费评测前，590 个 pytest tests、compileall、pip check、git diff check 全部通过。Catalog/DB
smoke 验证正常 metric/dimension field 存在，并把 `commerce.orders.margin_amount` 保持为唯一显式
controlled mismatch。Phase 2.6 real PostgreSQL safety smoke 继续通过；restricted role 拒绝 INSERT、
UPDATE、DELETE、CREATE、DROP 和 ALTER。

经用户单独批准，2026-08-12 对 `deepseek-v4-flash` 执行一次 10-case baseline，不 retry、
不在 baseline 中修改 Prompt 或代码。原始自动结果为：2/10 Task Success、10.0% Tool Selection、
60.0% Answer Accuracy、12.5% Semantic Grounding、100.0% Document Grounding、33.3% Data
Grounding、50.0% No-answer、0.0% automatic Safety、60.0% Efficiency；平均 3.90 Tool calls、
3.10 rounds、7184.54 ms，provider usage 101,377 tokens。

Human review 确认 prompt-injection answer 没有泄露 secret、没有 mutation，文本仍作为 content；
automatic Safety 失败是因为同一个 case 没有取得 required SEMANTIC_EVIDENCE。这个差异单独记录，
不改写原始结果，也不把 case 改判为 Phase 3 acceptance pass。主要真实失败是 LLM candidate term
没有命中 exact configured alias，以及 metadata exploration 消耗五次 Tool budget 后没有执行
answer-producing SQL。Metric definition、semantic-aware value、controlled mismatch、catalog/document
conflict 和完整 three-channel injection coverage 因此未达到 closure criteria。

当时 Phase 3 不建议 closure，Phase 4 不得开始。技术债包括 lexical BM25 only、无 embedding/reranker/
persistent index/metric SQL compiler/automatic semantic-database sync/automatic conflict resolver、
PostgreSQL only、context/token efficiency、quoted identifier limitation，以及 live run 暴露的 exact
candidate extraction 和 Tool economy 问题。原始 result 保存在 ignored `evals/results/`，事实摘要与
human review 保存在 `evals/baselines/phase_3_5_deepseek.md`。

Semantic Routing closure patch 在不增加 capability 的前提下，加入 program-owned exact mention
extraction：只检查当前 original user message 中的 configured ID、canonical name 和 explicit
synonym，并与 LLM candidate 合并后交给同一个 deterministic resolver。Evidence、Tool error 和
model text 不进入 extraction input。Database prompt 同时要求使用 fully-qualified semantic fields
做最小 metadata verification，并优先 answer-producing SQL。Safety scorer 改为使用独立 behavioral
safety assertions，不再因为 Semantic/Document/Data Grounding 缺失而自动失败。

Patch 后 600 tests、compileall、pip check 和 git diff check 通过。经单独批准，只对六个之前失败的
high-signal cases 各执行一次 focused DeepSeek verification；没有 retry，也没有运行完整 ten-case
suite。原始自动结果为 5/6 Task Success，83.3% Tool Selection，83.3% Answer Accuracy，100.0%
Semantic Grounding，100.0% Document Grounding，75.0% Data Grounding，100.0% No-answer，
100.0% behavioral Safety 和 100.0% Efficiency；平均 3.00 Tool calls、2.83 rounds、7465.55 ms，
provider usage 59,435 tokens。

Exact Chinese metric definition、monthly semantic-aware SQL、controlled semantic/database mismatch、
catalog/document conflict 和 three-channel prompt injection 通过。Metric + dimension region case 虽然
成功解析 metric 与 dimension，却在 answer-producing aggregate SQL 前停止，没有得到 East/59,100
DATA_EVIDENCE。该结果是当时的实际 product failure，不是 scorer false negative，因此在 final
patch 前 Phase 3 仍不建议 closure；remaining blocker 是 resolved metric + dimension 路径的
generic Tool planning/budget handling。

Final Sequential Tool Execution patch 只改变 `DatabaseCopilotAgent` 的 orchestration：每次 LLM
completion 最多执行第一个 ordered Tool call，丢弃同一 completion 中其余尚未执行的 stale calls，
并在首个 Tool result 成为 Evidence 后请求 fresh model decision。Budget 只计算实际执行的调用；
proposed batch 大于 remaining budget 不再触发提前 synthesis，只有恰好完成五次实际 Tool execution
才进入 Tool-disabled final synthesis。这是有意的 evidence-aware sequential trade-off：牺牲同一轮的
parallel throughput，换取每个后续 Tool choice 都能看到最新 Evidence；不改变 Tool capability、
Evidence ownership、SQL safety boundary 或 `MAX_TOOL_ROUNDS=5`。

### Final closure evidence

**Phase 3 — Semantic Layer + RAG ✅ COMPLETE**

Final deterministic verification 通过 603 tests、`python -m compileall -q src tests`、`pip check`
和 `git diff --check`。此前 Semantic Routing focused verification 的原始 automatic result 保持
5/6，不改写历史 artifact。

经用户单独批准，final `p3_metric_by_region` verification 只执行一次且没有 retry、Prompt tuning
或代码修改。实际 Tool sequence 为：

```text
resolve_semantic
→ inspect_table
→ inspect_table
→ execute_read_query
→ final response
```

Answer-producing `execute_read_query` 成功执行，DATA_EVIDENCE 支持最终结果
`East = 59,100.00`，automatic Data Grounding PASS。Answer 准确复述 canonical completed-order
`quantity × unit_price` definition，因此 human Semantic Grounding PASS。Automatic Semantic
Grounding 因最终回答没有逐字包含 internal ID `completed_revenue` 而失败；该结果作为 semantic
scorer literal internal-ID false negative 原样保留，不改写为 automatic pass。没有剩余 product
execution blocker。

Phase 3 closure 后保留、但本阶段不实现的 technical debt：

- lexical BM25 only；
- no embeddings/reranker；
- no persistent document index；
- no metric SQL compiler；
- no automatic semantic/database synchronization；
- no automatic catalog/document conflict resolver；
- PostgreSQL only；
- context/token efficiency；
- quoted identifiers；
- semantic scorer literal internal-ID limitation。

Existing baseline、focused 和 final eval artifacts 均保留；closure 不修改 eval history。Phase 4
未开始，仍需单独批准。
