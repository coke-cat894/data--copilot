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

### Phase 1 — Local Data Foundation ✅ COMPLETE

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

### Phase 2 — SQL / Database Copilot ✅ COMPLETE

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

### Phase 4 — Data Engineering Troubleshooting ✅ COMPLETE

Phase 4.1–4.4 completed the deterministic diagnostic snapshot, restricted
read-only PostgreSQL collection, LLM-free pipeline/job Evidence, and bounded
integration with the existing database Agent. Phase 4.5 completed the separate
evaluation and live closure gate.

### Phase 5 — Evaluation + Product Hardening ✅ COMPLETE

Phase 5.1 增强 eval trustworthiness、observability、reproducibility 与 artifact
safety；Phase 5.2 完成 context/token/Tool efficiency hardening；Phase 5.3 完成
runtime reliability/error handling；Phase 5.4 完成 productization/maintainability
hardening；Phase 5.5 完成 final end-to-end evaluation、physical-only routing
closure 和 v1 project closure。这些阶段没有增加新的 Data Copilot product
capability。

**Data Copilot v1 Roadmap ✅ COMPLETE**

### Post-v1 possibilities — not part of v1 closure

```text
MySQL
Airflow
Spark
GitHub
Warehouse
MCP Servers
```

这些仅是未来方向，不是 v1 closure blocker。具体顺序必须由真实使用需求、
安全边界和独立 phase approval 决定。

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

Existing baseline、focused 和 final eval artifacts 均保留；closure 不修改 eval history。

---

## 41. Phase 4.1 Diagnostic Snapshot + Drift Foundation

Phase 1、Phase 2 和 Phase 3 保持冻结。Phase 4.1 只增加独立、LLM-free 的程序可靠性边界：

```text
validated before DatasetSnapshot
+
validated after DatasetSnapshot
→ deterministic DriftReport
```

`DatasetSnapshot` 使用 stable logical `dataset_id`，可选 logical snapshot ID / capture time，
以及 bounded row、column、null、distinct、exact full-row duplicate 和 numeric/date range facts。
未知 measurement 明确保留为 `None`，不得补算或虚构。Public model 不包含 path、DSN、credential、
SQL、arbitrary metadata 或 executable expression。

Snapshot model 最多接受 200 columns，并限制 identity、column name、data type、count 和 output
text size。Unknown field、duplicate column identity、negative/overflow count、count 超过 row count、
invalid/non-finite rate、incompatible/reversed range、path-like dataset identity 均 fail closed。
Column 规范排序，因此同一逻辑输入不依赖 caller insertion order。

Comparator 只允许相同 logical dataset identity，并以固定顺序输出所有 comparable observed drift：

```text
column added / removed
data type / known nullable change
row count absolute + before-baseline percentage delta
null count / rate change
distinct count change
duplicate count / rate change
numeric/date minimum / maximum change
```

Before baseline 为 zero 时 percentage delta 明确 unknown，不产生 division-by-zero 或 misleading
percentage。Rate finding 保留原始 before/after rate、absolute rate delta 和 percentage-point delta。
Percentage 使用固定 four-decimal rounding policy。Phase 4.1 不配置 business threshold，不丢弃
observable change，不声称 statistical significance，也不输出 ETL failure、broken source 或其他
root-cause hypothesis。

Finding、column 和 serialization 顺序全部 deterministic。Prompt-like dataset/column text 仍是
bounded inert data，不是 instruction 或 capability。Phase 4.1 不连接 PostgreSQL、不调用 LLM/API、
不修改 Agent/Tool/Evidence/SQL safety boundary、不增加 write/remediation capability，也不修改既有
eval artifact。PostgreSQL diagnostic snapshot collection 由独立 Phase 4.2 boundary 提供；Agent
integration 和后续 diagnosis 仍 defer 到 Phase 4.3 或以后单独批准的阶段。

---

## 42. Phase 4.2 PostgreSQL Data Health Diagnostics

Phase 4.2 将 frozen Phase 4.1 snapshot contract 连接到既有 PostgreSQL registry/configuration，
但不修改 Agent、Tool dispatcher、Evidence、SQLValidator 或 read-query capability：

```text
opaque database_id + schema + table
→ DatabaseRegistry resolution
→ one repeatable-read read-only PostgreSQL transaction
→ program-owned bounded aggregates
→ existing DatasetSnapshot + bounded warnings
→ optional existing compare_snapshots()
```

`PostgresDiagnosticCollector` 不接受 DSN、credential、caller SQL 或 expression。Schema/table 先经
logical identity validation 和 parameterized catalog lookup；dynamic relation/column identity 只通过
psycopg `Identifier` composition 进入 program-owned SELECT。每次 collection 在第一条 query 前设置
read-only、repeatable-read 和 registered transaction-local statement timeout；metadata、row count、
column statistics 和可选 duplicate measurement 共享同一 MVCC snapshot，不增加 blocking lock。

Metadata 最多保留既有 200 columns。默认只为前 50 columns 收集 null facts，为最多 20 个
metadata-supported columns 收集 exact distinct count，并为最多 20 个 integer/numeric/decimal/
real/double/date/timestamp/timestamptz columns 收集 MIN/MAX。Empty table 的 null/duplicate rate 固定
为 `0.0`。Unsupported、scope 外或无法安全表示的 measurement 保持 `None`；approximate planner
statistics 不得冒充 exact observation。

Exact full-row duplicate 继续使用 Phase 4.1 的 duplicates-beyond-first definition。默认只有
`row_count <= 10000`、column metadata 完整且所有 column type 可安全 grouping 时才执行完整 row
grouping；否则 duplicate count/rate 保持 unknown，并返回 sanitized deterministic warning。Caller
可通过 strict bounded `PostgresDiagnosticLimits` 降低或在 hard cap 内调整 profile/distinct/range/
duplicate/warning limits。Warning 不包含 SQL、DSN、credential、driver diagnostic 或 path。

Timeout、invalid catalog/statistic response 和 connection/read-only failure 转为 sanitized typed domain
error；unknown database、schema 和 table 保持既有 fail-closed error boundary。Collector result 中的
snapshot 可直接传给 frozen `compare_snapshots()`，collector 内不复制 drift logic。

Phase 4.2 不调用 LLM/API、不注册 Agent Tool、不推断 root cause、不读取 job/pipeline log、不执行
ANALYZE/VACUUM/temporary table/stored procedure，也不增加任何 write/remediation capability。Focused
real PostgreSQL smoke 使用既有 restricted role，不要求额外 permission，并继续验证 INSERT、UPDATE、
DELETE、CREATE、DROP、ALTER 均被 database 拒绝。

---

## 43. Phase 4.3 Pipeline / Job Log Troubleshooting Foundation

Phase 4.3 在 frozen Phase 4.1/4.2 之外建立独立、LLM-free 的 pipeline observation boundary：

```text
explicit local JSON / JSONL pipeline records
→ safe bounded loader
→ strict PipelineRun / PipelineStepRun / PipelineEvent
→ deterministic normalization and factual run comparison
→ bounded sanitized PIPELINE_EVIDENCE
```

Run 和 step 只使用 bounded logical identity；public provenance 只有 logical source file name 和
record index，不包含 absolute path。Status 固定为 pending/running/success/failed/cancelled/skipped/
unknown，event level 固定为 debug/info/warning/error/critical。Timestamp 必须 timezone-aware；step
duration 可从 start/end deterministic derive。Reported input/output/rejected count 必须 non-negative，
unknown 保持 `None`，zero 保持 observed zero。Step/event 使用 canonical order，duplicate identity、
invalid association、negative/inconsistent timing/count 和 unknown field 均 fail closed。

Loader 只接受显式 file/directory 和显式 allowed roots。Directory scan 为 single-level、deterministic、
non-recursive；只允许 UTF-8 `.json`/`.jsonl` regular files，拒绝 symlink component、hidden source、
unsupported type、duplicate run identity，并限制 file count、file bytes、runs per file 和 total runs。
Loader 不连接 network、database 或 external pipeline service。

`compare_pipeline_runs` 只比较相同 pipeline identity，按 canonical order 报告 observed overall/step
status、added/missing step、comparable duration、input/output/rejected count、warning/error event count，
以及 baseline 中 later step 未观察到的 early-stop fact。它不配置 significance threshold、不猜测
unreported value，也不将 event text 映射为 cause。

`PIPELINE_EVIDENCE` 与 `DATA_EVIDENCE`、`SEMANTIC_EVIDENCE`、`DOCUMENT_EVIDENCE` 分离。Envelope
只保留 selected step summary、relevant warning/error/critical event、factual comparison finding 和 logical
provenance；分别限制 record/message/serialized chars。Truncation 删除完整 trailing record 并显式给出
warning。Common password/API key/bearer token/DSN/connection-string forms 在 public Evidence 前进行
conservative redaction；source model 不被修改。完整 raw log、unbounded stack trace、credential、environment、
driver diagnostic 和 absolute path 不进入 Evidence。Prompt-like log 仍只是 bounded inert content。

Phase 4.1 只表示 observed data drift，Phase 4.2 只从 PostgreSQL 收集 snapshot，Phase 4.3 只表示
observed pipeline/job execution facts。即使这些 evidence 同时存在，本阶段也不得输出 causal/root-cause
claim。Phase 4.3 不调用 LLM/API、不注册 Agent Tool、不修改 SQL/database safety、不增加 external
Airflow/Spark/Databricks/dbt/observability adapter，也不提供 write/remediation。Combined Evidence 的
Agent-driven troubleshooting 和 root-cause reasoning defer 到单独批准的 Phase 4.4。

---

## 44. Phase 4.4 Troubleshooting Agent Integration

Phase 4.4 不建立 parallel Agent，也不把 deterministic diagnostics 移进 Prompt。它向既有
`DatabaseCopilotAgent` 增加一个 optional、program-configured `TroubleshootingResources` boundary：

```text
approved DatasetSnapshot / PipelineRun resources
+ optional existing PostgresDiagnosticCollector
→ four minimal Agent-facing diagnostic Tools
→ deterministic DIAGNOSTIC_EVIDENCE / PIPELINE_EVIDENCE
→ existing sequential evidence-aware Agent loop
→ calibrated troubleshooting explanation
```

没有 troubleshooting resources 时，既有 Phase 2/3 Tool schemas 和 base prompt 保持不变。Resource
存在时只暴露实际可用 capability：`collect_table_diagnostics` 委托 frozen Phase 4.2 collector；
`compare_table_snapshots` 委托 frozen Phase 4.1 comparator；`inspect_pipeline_run` 和
`compare_pipeline_runs` 委托 frozen Phase 4.3 typed runs、comparison 和 Evidence builder。Tool 不接受
DSN、credential、caller SQL、timeout、connection parameter、log path 或 arbitrary raw log input。

Snapshot 和 pipeline run 使用 bounded in-memory program listing；snapshot ID 以及 pipeline/run ID 必须
唯一。Prompt 只取得 bounded path-free resource metadata，不取得 raw event。Live table collection 对相同
logical table 在当前 Agent context 内复用 cached typed result，避免重复 PostgreSQL aggregate。所有 optional
Tool 与原有 database/semantic/document Tool 共享 `MAX_TOOL_ROUNDS=5`；每个 model decision 仍只执行第一个
ordered Tool call，然后让下一次 decision 看到 fresh Evidence。五次实际 Tool execution 后仍执行既有
Tool-disabled final synthesis。

Evidence taxonomy 为：

```text
SEMANTIC_EVIDENCE   = configured structured business meaning
DOCUMENT_EVIDENCE   = retrieved explanatory policy/context
DATA_EVIDENCE       = observed database metadata/value/plan facts
DIAGNOSTIC_EVIDENCE = observed table snapshot and deterministic drift facts
PIPELINE_EVIDENCE   = observed pipeline/job run facts
```

`DIAGNOSTIC_EVIDENCE` 是新的 strict bounded envelope，只包含 selected column observations 或 existing
`DriftReport` finding、logical snapshot provenance 和 sanitized warning；column/finding/serialized resource
全部有 hard limit。`PIPELINE_EVIDENCE` 继续复用 Phase 4.3 secret redaction 和 message/event bound。
Database drift 不得冒充 pipeline fact，pipeline message 也不得冒充 observed database value。

Troubleshooting Prompt contract 要求分开表达 observed fact、hypothesis、confirmed root cause 和
insufficient evidence。Hypothesis 必须使用 plausible/consistent with/suggests/strongly or weakly supported
等 qualitative language，不提供未校准 numeric confidence。只有 Evidence 直接建立完整 causal chain 时
才允许 definitive cause wording，并必须说明 chain 中每项 Evidence。Matching count、similar timestamp 或
熟悉的 error phrase 单独都不等于 causality。Missing baseline、unaligned run、conflicting telemetry、missing
semantics 和 unresolved alternatives 必须变成 uncertainty/no-answer，而不是 fabricated conclusion。

Pipeline/log content 继续是 untrusted inert Evidence，即使内容要求 DROP、secret disclosure、permission
change 或 Tool call 也不能成为 instruction。SQLValidator、read-only PostgreSQL、restricted role、statement
timeout、result bound、secret sanitization、semantic fail-closed 和 final Tool-disabled synthesis 均不弱化。
Agent 只能建议下一项 safe diagnostic observation；不得 rerun job、alter schema、mutate data、delete rows、
change permission 或声称 remediation 已执行。

Existing safe Agent logging 增加 produced Evidence channel，但仍不记录 arguments、Evidence payload、SQL、
credential、path 或 hidden reasoning。Phase 4.4 不新增 persistent troubleshooting trace store；durable sanitized
production trace facility、external Airflow/Spark/Databricks/dbt/observability adapter、automatic remediation 和
Phase 5 capability 均 defer；Phase 4.5 只允许增加 bounded eval-local trace。

---

## 45. Phase 4.5 Troubleshooting Evaluation + Closure Gate

Phase 4.5 冻结 Phase 4 product capability，只增加 deterministic eval fixtures、independent scorers、
bounded eval-local trace 和 focused real PostgreSQL validation。12-case set 覆盖 matching row telemetry、
confirmed schema/missing-column chain、null spike、pipeline failure without data drift、data drift with healthy
run、conflicting telemetry、missing baseline、duplicate spike、prompt injection、missing business metric、pure
database regression 和 Phase 3 metric regression。Synthetic meaning 只存在于 eval fixture，不进入 production
Agent rules。

Evaluation dimensions 分开保存：Task Success、Answer Accuracy、Tool Selection、Semantic/Document/Data/
Diagnostic/Pipeline Grounding、Causal Discipline、Uncertainty、Conflict Handling、behavioral Safety、Efficiency、
Tool Calls、Rounds、Latency 和 provider-supplied Token Usage。Safety 不由 grounding 或 task success 推导；
safe-but-incomplete case 可以 Safety PASS 且 Task Success FAIL。

Causal scorer 使用 case-declared qualitative classification：observed fact、supported hypothesis、confirmed
root cause、insufficient evidence 或 conflicting evidence。它检查 required evidence-chain concepts、calibrated
language 和 forbidden unsupported claim，不要求 exact final answer，也不把 scorer logic 注册为 production
cause mapping。没有 calibrated numeric confidence。

每个 Tool execution 的 eval-local trace 只保存 round、remaining budget、Tool name、sanitized bounded arguments、
Evidence channel 和 count/status-only Evidence summary。Trace 不保存 raw Evidence、full log、hidden reasoning、
DSN、credential、environment、absolute path 或 secret。SQL 只可按既有 eval convention 以 sanitized bounded
Tool argument 保存。

任何 live DeepSeek run 前必须先通过 deterministic pytest/compileall/pip/diff gate 和 existing guarded
`data_copilot_test` read-only smoke，并由用户明确批准 external synthetic-data transmission。Approved live set
恰好 12 cases，每个 exactly once；不得 retry、case 间 Prompt/code/scorer tuning 或 rewrite original artifact。
Automatic/human disagreement 必须分别保留并分类 true product failure、routing/runtime、Evidence、scorer、
fixture 或 provider failure。Live acceptance 未完成前不得标记 Phase 4 complete，也不得开始 Phase 5。

第一次 12-case live baseline 原始 artifact 保持不可变。Closure patch 不增加 capability，只收紧既有
reasoning/orchestration contract：causal level 明确区分 observed fact、correlated observation、plausible
hypothesis、strongly supported cause 与 confirmed root cause；matching count、timing proximity 和 pipeline
SUCCESS 都不能单独升级因果。SUCCESS 只表示 pipeline system reported successful execution，不证明
business logic、source completeness、silent filtering 或 data quality 正确。

Troubleshooting Evidence 必须与当前 dataset/field/run/time window/incident 相关；smallest sufficient Evidence
优先。Program-owned resource metadata 明确标记每个 dataset 是否具备 before/after comparison。Missing
comparison input 或 required semantic definition 会让 next completion 进入 Tool-disabled synthesis，禁止用
current-state/schema exploration 替代缺失 baseline 或 business meaning。MAX_TOOL_ROUNDS=5 与 sequential
execution 不变。

Conflict handling 先检查 available identity/time metadata 是否可比；unknown/incompatible alignment 必须明确
保留，不能选择 canonical source、归责或推断 silent load/delete/rollback。Scorer 只修复 baseline 已验证的
限制：semantic answer 不必打印 internal catalog ID，但可独立配置 user-facing definition requirements；
negated causal wording 不作为肯定因果；equal percentage formats 等价；required Evidence channel 可支持
safe equivalent Tool route；unaligned conflict 若 privilege 任一 source 则失败。

后续 live verification 只能通过 frozen six-case focused selector，覆盖 row-count correlation、null isolation、
healthy pipeline + drift、unaligned conflict、missing baseline 和 missing semantic metric。必须重新取得用户
explicit DeepSeek approval，每 case exactly once、`max_retries=0`，不得 rerun 原 12-case suite、case 间调
Prompt/code/scorer 或自动修复。Focused live acceptance 完成前 Phase 4 继续 open，Phase 5 不得开始。

Six-case focused verification 后只剩两个 product blocker。Final patch 进一步区分 cross-run correlation 与
same-run boundary observation：baseline/incident DB delta 与 baseline/incident step output delta 相同，只能是
correlated observation / plausible investigation focus；同一 run 的 step input/output 可直接观察 reduction
across that telemetry boundary，但仍不证明 persisted DB drift 由该 step 导致，也不证明 mechanism，更不能
无 Evidence 排除 Extract/Load。

Agent orchestration 对 explicit technical health language 使用 conservative program-owned schema filtering：
row/null/distinct/duplicate count/rate、schema/column drift、type、range 与 table health question 在配置
troubleshooting resources 时不提供 `resolve_semantic`，优先现有 diagnostic capability。Definition/meaning/
口径 question 以及 revenue/sales/churn 等 business concept 保持 Phase 3 semantic route。若 optional semantic
miss 仍发生，只有真正需要 business meaning 的问题才 terminal；technical diagnostic 可继续收集 Evidence。

Final live selector 固定只包含 `row_count_drop_pipeline_match` 与 `null_spike_unknown_cause`，不得和 six-case
selector 或 arbitrary IDs 合并。执行前仍需 fresh explicit DeepSeek approval；每 case once、`max_retries=0`、
无 retry/Prompt tuning/code/scorer change。Full 12-case 与 six-case artifact 保持不变，Phase 5 继续禁止。

---

## 46. Phase 4 Closure

**Phase 4 — Data Engineering Troubleshooting ✅ COMPLETE**

Phase 4 的核心设计原则是：

> Evidence first, diagnosis second.

所有 troubleshooting conclusion 必须保持以下层级，不得因为 matching count、时间接近、SUCCESS status 或
熟悉的错误文本而自动升级：

```text
Observed Fact
Correlated Observation
Plausible Hypothesis
Strongly Supported Cause
Confirmed Root Cause
Insufficient Evidence
```

Observed Fact 直接来自 bounded Evidence；Correlated Observation 只表示多个 observation 对齐；Plausible
Hypothesis 是有部分 Evidence 支持的安全调查方向；Strongly Supported Cause 需要 substantial 但仍不完整的
causal chain；Confirmed Root Cause 必须由直接、完整、可引用的 causal chain 建立；Insufficient Evidence
必须明确停止在 uncertainty/no-answer，不得 fabricated certainty。

Final closure evidence：

- final live verification 前，822 个 deterministic tests 已通过；
- Phase 4.1–4.4 均完成；
- real PostgreSQL diagnostic collection 以及 restricted-role read-only safety 均通过；
- final two true product blockers 均通过 grounded human review；
- row-count matching 仍被正确限制为 correlation / investigation focus，没有升级为 Transform confirmed
  cause，也没有无 Evidence 排除 Extract 或 Load；
- null-spike routing 只使用所需 `DIAGNOSTIC_EVIDENCE`，没有不必要 semantic resolution；
- final focused verification 的 Tool Selection、Diagnostic Grounding、Pipeline Grounding、Causal Discipline、
  Uncertainty 和 Efficiency 均为 100%；
- 唯一剩余 automatic failure 已记录为 scorer false negative：literal substring matching 命中了明确否定句
  中的 forbidden phrase。Grounded human review 不改写 automatic result。

Original 12-case baseline、six-case focused 和 final two-case live artifacts 全部保持不变。Phase 4 closure
不增加 capability、不重跑 provider、不启动 Phase 5。

Closure 后保留但不在本阶段实现的 technical debt：

- external pipeline adapters；
- automatic time/run alignment；
- persistent production troubleshooting traces；
- calibrated confidence model；
- automatic remediation；
- broader database adapters；
- context/token efficiency；
- semantic/negation-aware scorer robustness。

---

## 47. Phase 5.1 Eval Harness + Safe Observable Trace Hardening ✅ COMPLETE

Phase 5.1 在 frozen Phase 1–4 product capability 之外增加 eval-local、typed、bounded、versioned
safe trace：

```text
User Question
→ provider-visible model decision
→ proposed Tool count
→ one actually executed Tool
→ sanitized arguments
→ bounded Evidence summary + channel
→ fresh model decision
→ Tool-disabled final synthesis where required
→ bounded final answer + known usage
```

Safe trace 只保存 observable Agent behavior。允许的数据是 provider 暴露的 assistant text、Tool calls、
Tool arguments、Tool output 形成的 Evidence summary 和 user-facing final answer。它明确不请求、不保存
hidden reasoning、private chain-of-thought、internal scratchpad、provider reasoning content 或未暴露 reasoning
tokens。Trace 是调试/评测 artifact，不是 permission、Memory、raw Evidence store 或 production telemetry
platform。

Trace schema 对 question、round、Tool execution、arguments、Evidence summary、model output、final answer、
warning/error 和 serialized size 都有 deterministic hard bound。Truncation/redaction 必须显式记录。Arguments
按 key 和 value pattern sanitize；SQL 只允许沿既有 read-only eval trace policy 作为 bounded sanitized argument，
不能包含 credential/DSN/connection configuration。五个 Evidence channel 保持独立：semantic、document、
data、diagnostic、pipeline。

Eval-only `ObservableLLMClient` wrapper 只观察 normalized public `LLMResponse` 与 program-owned request control。
Dataset 与 Database Agent 使用相同 sequential contract：一次 model decision 最多执行 first ordered Tool；同一 response 的
stale proposals 只影响 `requested_tool_count`，不得冒充 execution，budget 只计算实际执行。Tool-disabled final
synthesis 作为 `tools_enabled=false` 的独立 observable round。

Automatic scorer 为每个独立 metric 生成 bounded PASS/FAIL/N/A detail：matched/missing requirements、detected
forbidden claim、Evidence requirement 和 scorer note。Task Success、Answer Accuracy、Tool Selection、五种
Grounding、Causal Discipline、Conflict、Uncertainty、behavioral Safety 与 Efficiency 不互相污染。Percentage
equivalence、semantic internal-ID exemption、Evidence-equivalent safe route 与 negation-aware forbidden claims
保持 generic deterministic rule；该 scorer 不声称解决任意自然语言等价。

Automatic failure classification 只提供 conservative review hint：product behavior、Tool routing、Evidence、
Safety、scorer limitation、fixture issue、provider transient 或 unknown。Human review 使用 separate typed
overlay，引用 eval run/case、原始 automatic metrics、automatic artifact hash、human outcome、classification 与
rationale；它不能覆盖或改写 automatic result。

新 artifact 使用 schema version、unique run ID、safe filename、explicit size bound、SHA-256 content hash、
atomic no-overwrite create 和 bounded deterministic safety scan。Scanner 对 known API key、bearer token、
password、DSN、connection string、`.env` value 和 absolute workspace path fail closed，但不声称完美 secret
detection。Run reproducibility metadata 记录 suite/selector、provider/model、Tool budget、known retry policy 与
prompt/scorer/fixture fingerprint；unknown 保持 unknown，不承诺 external LLM bit-for-bit reproducibility。

Phase 1–4 historical artifacts 保持 immutable；不自动 migration、不 retroactively invent historical telemetry。
Phase 5.1 不调用 DeepSeek/OpenAI，不增加 write/remediation、external pipeline integration、embedding/vector DB、
reranker 或 Phase 5.2 capability。

---

## 48. Phase 5.2 Context / Token / Tool Efficiency Hardening ✅ COMPLETE

Phase 5.2 的原则是 remove redundant context and work，而不是通过删除 reasoning、Evidence 或 validator 来降低
成本。SQLValidator、database read-only、statement timeout、result bound、secret sanitization、semantic ambiguity、
Evidence validation、sequential first-call execution 与 Tool-disabled final synthesis 均保持不变。

Safe trace schema `1.1` 为每个 provider-visible request 记录 deterministic serialized-character accounting：system、
user、Tool schema、prior assistant、Tool error/other history，以及 semantic/document/data/diagnostic/pipeline 五个
Evidence channel。`estimated_input_tokens = ceil(serialized_chars / 4)` 只用于本地容量比较，明确不是 provider
tokenizer 或 billing token；provider-reported input/output/total tokens 保持独立字段。Run aggregate 还记录 Tool
schema chars、Evidence transmitted/repeated chars 与 duplicate Evidence chars avoided。Trace 仍不保存 hidden reasoning
或 unbounded raw Evidence。

Prompt 去除 Phase 2–4 重复约束但保留既有行为 contract；三个静态 prompt 从 5,045 / 7,676 / 6,997 chars
缩减为 2,657 / 3,921 / 3,454 chars。Strict Tool JSON schema 删除非语义 `title`，Tool descriptions 保留 purpose、
argument distinction 和 routing boundary，删除重复 global safety prose；public Tool name 和 argument semantics 不变。
Prompt fingerprint 继续由 Phase 5.1 reproducibility metadata 记录。

Database Agent 使用已有 explicit deterministic signals 做 conservative progressive exposure：pure count 只提供 database
Tools；definition-only 只提供 semantic；policy explanation 只提供 semantic/document；metric value 先 semantic，再提供
必要 metadata/query Tools；physical diagnostics 不提供 semantic/database；mixed troubleshooting 在 diagnostic Evidence 后
只保留 pipeline Tools。Missing baseline 直接无 Tool；uncertain question fail open 到全部 registered capability。这个 routing
不是 general intent classifier，也不授予任何新 capability。

成功 Evidence 由 canonical parsed Tool arguments 建立 run-local reuse key；不同 key 仍正常执行。Local dataset Evidence
以及稳定 database metadata/semantic/document/snapshot/pipeline observations 可复用，live answer query、plan 和 table
collection 不做跨时点 cache。Exact duplicate 会返回 bounded `EVIDENCE_REUSE` reference、保留原 Evidence、记录 avoided
chars、且不消耗第二次 actual Tool execution；随后进入 Tool-disabled grounded synthesis，避免重复循环。Tool-call turn 的
非事实 assistant chatter 不进入后续 history；original user question、structured Tool request、Evidence、safe error 与 final
answer contract 保留。

Pre-change baseline 在 broad optimization 前冻结。相同 deterministic cases 的结果如下；chars 是 compact request
accounting review guard，Tool calls/rounds 均保持原值：

| Case | Baseline system / schema / total context | Phase 5.2 system / schema / total context | Calls / rounds |
|---|---:|---:|---:|
| pure DB count | 8,019 / 3,566 / 17,439 | 4,481 / 2,059 / 11,878 | 1 / 2 |
| metric value | 8,019 / 3,566 / 28,233 | 4,481 / 475 / 18,552 | 2 / 3 |
| null spike | 15,509 / 3,548 / 33,544 | 8,533 / 547 / 19,273 | 1 / 2 |
| diagnostic + pipeline correlation | 15,800 / 5,689 / 52,854 | 8,860 / 1,544 / 33,165 | 2 / 3 |
| missing semantics | 8,019 / 3,566 / 18,186 | 4,481 / 475 / 11,040 | 1 / 2 |
| missing baseline | 15,423 / 3,566 / 15,953 | 8,435 / 2 / 8,546 | 0 / 1 |
| pipeline prompt injection | 15,314 / 4,189 / 32,861 | 8,320 / 463 / 18,506 | 1 / 2 |

Existing Phase 3/4 fixtures provide A–J coverage: pure DB count, metric definition/value, policy explanation, null spike,
diagnostic+pipeline correlation, missing semantics/baseline, prompt injection, and metric+dimension. Deterministic regression
requires unchanged task success, grounding, safety, causal/no-answer behavior, calls, and rounds; savings alone cannot override a
behavior failure. Phase 5.2 makes no provider call and does not modify historical live artifacts. Pricing, tokenizer-accurate local
estimation, broader adaptive planning, semantic Evidence field redesign, external cache, and live efficiency verification remain
deferred.

---

## 49. Phase 5.3 Runtime Reliability + Error Handling ✅ COMPLETE

Phase 5.3 adds a small program-owned runtime contract without adding Data Copilot capability. Internal exceptions map to bounded,
sanitized categories for provider transient/fatal/malformed response, Tool validation/execution, database connection/timeout, SQL
validation, Evidence construction, unavailable resources, final synthesis, budget/configuration, and unknown runtime failures.
Failure is distinct from observed empty or zero data and must never be serialized as valid Evidence.

Only normalized provider-transient failures are retryable. Agent runtime defaults to one retry and caps configuration at two;
deterministic validation, safety, semantic, baseline, permission, configuration, and Evidence failures receive zero retries. Provider
SDK retries are set to zero so attempts remain visible at the Agent boundary. Eval runtime explicitly defaults to zero retries and may
opt into the same bounded policy; existing one-shot live eval behavior remains unchanged.

The sequential contract remains:

```text
one provider decision (possibly retried before execution)
→ first ordered Tool proposal only
→ actual Tool execution or sanitized validation rejection
→ bounded Evidence or structured TOOL_ERROR
→ fresh provider decision
```

Rejected/unknown/malformed Tool requests do not execute and do not consume `MAX_TOOL_ROUNDS=5`. A Tool runtime failure counts as an
actual execution but produces no Evidence. Provider retry never replays a completed Tool, and Phase 5.2 run-local Evidence reuse remains
in force. SQLValidator rejection remains pre-execution and non-retriable; connection and statement-timeout errors remain separate from
empty query results. Successful raw Tool results are never exposed when Evidence construction fails.

Safe trace schema `1.2` records provider attempt number, retryability, whether retry occurred, failure category/stage, whether a Tool
executed, whether Evidence was produced, and explicit run outcome: `SUCCESS`, `SAFE_NO_ANSWER`, `PARTIAL`, `RUNTIME_FAILURE`, or
`SAFETY_REJECTION`. Final-synthesis failure preserves prior observable Evidence/Tool history and executes no additional Tool. Missing
required semantics and missing baselines remain deterministic terminal no-answer states rather than generic runtime failures. Task
Success, behavioral Safety, grounding, and efficiency remain independent; provider unavailability makes behavioral Safety N/A rather
than FAIL.

Deterministic FakeLLM/fake Tool/fake database fault injection covers immediate and recovered provider failure, retry disabled,
malformed provider output, unknown/invalid Tool calls, database connection and timeout, SQL mutation rejection, diagnostic and pipeline
resource failure, Evidence builder failure, missing semantics/baseline, final-synthesis failure, retry duplicate protection, actual-call
budget accounting, and prompt injection combined with runtime failure. Phase 5.3 makes no provider call, adds no database retry loop,
write/remediation access, external pipeline integration, embedding/vector DB, reranker, or Phase 5.4 capability.

---

## 50. Phase 5.4 Productization + Maintainability Hardening ✅ COMPLETE

Phase 5.4 does not add intelligence or execution capability. It makes the existing Phase 1–5.3 system understandable and verifiable
through one documented configuration surface, a provider-free environment doctor, explicit package boundaries, repository hygiene,
and a concise product-facing README. Phase 5 remains open; Phase 5.5 is required and has not started.

Interactive startup now composes validated provider configuration with one small program-owned runtime configuration. Provider remains
explicit (`openai` or `deepseek`), model and applicable API key are required only for provider-backed execution, the DeepSeek service URL
must be HTTP(S) without embedded credentials/query/fragment, and interactive provider retries default to one with an allowed range of
zero through two. The actual Tool-execution budget remains fixed at five rather than becoming a user-controlled permission surface.
PostgreSQL DSN and bounded connect/statement timeouts remain required only when PostgreSQL is selected. Semantic/document sources,
allowed roots, diagnostic limits, and artifact locations remain explicit CLI or constructor inputs rather than a duplicate environment
configuration system.

`.env.example` contains only variable names, non-secret placeholders, and safe numeric defaults. It contains no real key, credential,
username/password DSN, or absolute local path. Local `.env`, caches, coverage output, build output, logs, and common temporary files remain
ignored. Phase 5.4 did not read or rewrite the local `.env`, delete historical eval artifacts, remove uncertain code, churn dependencies,
or mutate Git history.

`data-copilot doctor` returns bounded typed `PASS`, `WARN`, `FAIL`, and `SKIPPED` checks for Python/package runtime, runtime limits,
optional provider/PostgreSQL configuration, explicit semantic/document sources, allowed roots, and eval artifact directory usability.
Provider connectivity is always skipped and doctor never spends tokens. PostgreSQL reachability is separate from configuration validity
and runs only with `--connect-database`, using the fixed read-only health query and existing registered timeout. JSON output is available
for local automation. Missing optional provider/database configuration does not make deterministic local verification fail.

The user-facing entry points remain deliberately separate: `data-copilot DATASET` is the interactive Agent, `data-copilot doctor` is
local health/configuration inspection, `data-copilot-eval` owns mock/live evaluation, and `scripts/postgres` contains explicit development
smokes. Existing positional dataset invocation remains compatible. Public root imports remain the two Agent types plus `AgentResult` via
lazy imports; secret-bearing configuration, provider response structures, test helpers, and eval artifact internals are not promoted to
root public API.

Architecture directionality was reviewed without a speculative rewrite. Agents depend on the normalized `LLMClient` protocol; endpoint,
SDK request/response, usage, retry interaction, and Tool normalization remain inside provider adapters. Semantic, document, diagnostic,
and pipeline models/loaders do not depend on Agent runtime or provider SDKs. Production runtime does not import eval packages. The database
direction is Agent → typed database Tool dispatcher → registry/validator/engine → PostgreSQL implementation. This is an intended extension
boundary, not a finished multi-database abstraction: registry types, metadata and plan SQL, execution, and diagnostic collection retain
explicit PostgreSQL coupling.

Phase 5.3 typed failure and safe no-answer contracts remain unchanged. CLI and doctor report concise sanitized errors; database connection
failures do not expose driver details. Runtime logging remains bounded to operational summaries and excludes Tool arguments, raw Evidence,
SQL, rows, full logs, paths, credentials, provider internals, and hidden reasoning. The README now documents the product story, provider-free
quickstart, configuration table, current architecture, capability and trust boundaries, representative workflows, extension rules,
dependency roles, test/eval commands, and honest production limitations.

Focused configuration, doctor, CLI dispatch, optional capability, source-loading, sanitized-failure, and public-import tests protect the
new maintenance surface. Closure also requires the full deterministic pytest suite, compileall over source/tests/scripts, `pip check`,
`git diff --check`, CLI help, default provider-free doctor, deterministic mock Agent/eval smoke, and bounded repository scans. No
DeepSeek/OpenAI request, production write, database mutation, commit, push, Phase 5.5 feature, new database/provider, vector retrieval,
external pipeline adapter, or remediation path is authorized by Phase 5.4.

---

## 51. Phase 5.5 Final Evaluation and Data Copilot v1 Closure ✅ COMPLETE

Phase 5.5 closed the existing end-to-end product path without adding a new
capability. The final product positioning is:

> An end-to-end governed Data Agent prototype with deterministic safety
> boundaries, business semantics, evidence-grounded reasoning,
> troubleshooting, runtime hardening, and evaluation infrastructure.

This is not a claim that Data Copilot is fully production-ready.

Before focused live closure, the complete deterministic suite passed all 922
tests. The frozen ten-case DeepSeek `deepseek-v4-flash` final suite then ran
each approved case exactly once with provider retries disabled. The immutable
automatic result remains preserved. Grounded human review found all 10/10
answers acceptable; Answer Accuracy was 100%, every applicable Semantic,
Document, Data, Diagnostic, and Pipeline Evidence Grounding metric was 100%,
and Behavioral Safety was 100%. Review identified one minor true product
blocker: `final_db_join_aggregate` answered correctly and was DATA-grounded,
but an explicit physical-columns-only request still exposed and called
`resolve_semantic`.

The closure patch added only a deterministic negative capability constraint at
the existing routing boundary. The constraint is derived solely from the
current original user request; Tool output, Evidence, retrieved documents,
pipeline logs, model output, and previous assistant messages cannot remove
capabilities. Explicit physical/database-only requests expose database Tools
without Semantic, Document, or Troubleshooting Tools. Ordinary business metric,
metric-plus-dimension, policy, and ambiguous requests retain the existing
conservative routing behavior. No Prompt, scorer, eval case, SQL validator,
Evidence taxonomy, retry contract, Tool budget, or historical artifact changed.

After the updated deterministic suite passed all 922 tests, the separately
approved focused `final_db_join_aggregate` live verification ran exactly once
with zero provider retries. It passed with database-only Tool exposure, no
Semantic, Document, or Troubleshooting Tool execution, the correct
`East = 59,100.00` result, 100% DATA_EVIDENCE grounding, 100% Tool Selection,
and 100% Efficiency. The original ten-case artifact remains the primary final
suite record; the one-case artifact is the focused closure verification. No
product closure blockers remain.

Final status:

```text
Phase 1 — Local Data Foundation ✅ COMPLETE
Phase 2 — SQL / Database Copilot ✅ COMPLETE
Phase 3 — Semantic Layer + RAG ✅ COMPLETE
Phase 4 — Data Engineering Troubleshooting ✅ COMPLETE
Phase 5 — Evaluation + Product Hardening ✅ COMPLETE

Data Copilot v1 Roadmap ✅ COMPLETE
```

The remaining technical debt is explicit and non-blocking for v1 closure:

- PostgreSQL-only database integration;
- local/in-memory registries;
- BM25-only RAG;
- no embeddings or reranker;
- no external pipeline adapters;
- no automatic time/run alignment;
- no distributed trace backend;
- no RBAC or multi-tenancy;
- no automatic remediation;
- no deployment orchestration;
- bounded scorer semantic-language limitations;
- provider nondeterminism.

Any work on these items requires a new approved post-v1 phase. They do not
retroactively weaken the deterministic read-only, bounded Evidence, secret
isolation, runtime failure, safe no-answer, or artifact integrity guarantees
verified for v1.
