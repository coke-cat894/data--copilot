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