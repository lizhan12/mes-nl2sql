# MES NL2SQL

基于 `FastAPI + LangGraph + PostgreSQL + pgvector` 的 MES 自然语言转 SQL 服务。

项目目标是把用户的中文业务问题转换成可执行的 PostgreSQL 查询，并通过表结构知识库、联表图、少样本示例和运行时规则降低 SQL 幻觉问题，适用于 MES 场景下的联表查询、统计分析和问数接口封装。

---

## 1. 项目概览

### 1.1 能力边界

本项目当前提供以下核心能力：

- 将自然语言问题转换为 PostgreSQL SQL
- 基于向量检索召回相关 MES 表结构和历史 SQL 示例
- 基于表关系图自动补全可行的 JOIN 路径
- 对生成 SQL 做安全校验，禁止写操作
- 对执行失败的 SQL 自动重试修复，最多 3 次
- 支持本地 Harness 闭环和数据库在线 Harness 闭环
- 已支持双库拆分：
  - 项目内部库：承载 pgvector、Harness 表、运行时知识
  - 业务执行库：承载 MES 业务表，生成 SQL 在此执行

### 1.2 适用场景

- 查询工单、料号、产线、工序、库存、设备、质量等 MES 业务数据
- 快速验证联表关系是否合理
- 对接管理后台、智能问答、报表平台或内部数据助手
- 沉淀失败案例并持续迭代规则

### 1.3 当前技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| Web 框架 | FastAPI | 提供 API 服务与 OpenAPI 文档 |
| Agent 编排 | LangGraph | 串联多节点推理与状态流转 |
| LLM（SQL 生成/修复） | DeepSeek 系列 | 负责 SQL 生成与执行失败修复 |
| LLM（意图理解） | Qwen2.5-7B-Instruct | 负责中文意图拆解 |
| Embedding | `BAAI/bge-large-zh-v1.5` | 用于表结构与示例检索 |
| 向量库 | pgvector | 运行在 PostgreSQL 中 |
| 配置管理 | pydantic-settings | 统一加载 `.env` |
| 数据库驱动 | `psycopg` / `asyncpg` | 执行 SQL 与连接 PG |
| 包管理 | uv | 推荐的依赖与运行方式 |

---

## 2. 架构说明

### 2.1 双库架构

当前项目已经按职责拆分为两套数据库连接：

| 连接 | 配置项 | 用途 |
|------|--------|------|
| 项目内部库 | `PROJECT_DATABASE_URL` | 存放 pgvector 集合、Harness 运行表、运行时知识 |
| 业务执行库 | `SQL_EXECUTION_DATABASE_URL` | 存放 MES 业务表，生成 SQL 在此执行 |
| 兼容旧配置 | `DATABASE_URL` | 若未显式配置双库，则作为兜底默认值 |

推荐配置方式：

```bash
DATABASE_URL=postgresql://user:pass@host:5432/mes
PROJECT_DATABASE_URL=postgresql://user:pass@host:5432/postgres
SQL_EXECUTION_DATABASE_URL=postgresql://user:pass@host:5432/mes
```

说明：

- `PROJECT_DATABASE_URL` 不应该混放业务查询表，建议专门用于项目内部表
- `SQL_EXECUTION_DATABASE_URL` 指向真实 MES 业务库
- 如果只配置 `DATABASE_URL`，项目仍可运行，但内部表和业务表会继续混在一起

### 2.2 启动初始化行为

服务启动时会在 `lifespan` 阶段自动执行以下动作：

1. 初始化表结构向量库 `mes_schema_embeddings`
2. 初始化示例向量库 `mes_few_shot_embeddings`
3. 编译 LangGraph 工作流
4. 如果启用了在线 Harness，则自动初始化 `nl2sql_*` 系列表

如果向量库已经有数据，则只做连通性检查并跳过重复写入。

---

## 3. 工作流详解

### 3.1 总体流程

当前实现不是 6 节点，而是 **7 节点** 工作流：

```text
用户问题
  -> 节点1 意图理解
  -> 节点2 并行检索
  -> 节点3 BFS 图扩展
  -> 节点4 Schema 组装
  -> 节点5 SQL 生成
  -> 节点6 安全校验
  -> 节点7 SQL 执行与修复
  -> 返回结果
```

其中第 7 节点会在 SQL 执行失败时自动触发修复重试。

### 3.2 节点职责

| 节点 | 名称 | 作用 |
|------|------|------|
| 1 | 意图理解 | 提取锚点表、搜索词、时间范围、筛选条件 |
| 2 | 并行检索 | 检索表结构知识和 few-shot 示例 |
| 3 | BFS 图扩展 | 根据锚点表扩展可联表路径并生成 JOIN 提示 |
| 4 | Schema 组装 | 只保留真正需要给 LLM 的表结构上下文 |
| 5 | SQL 生成 | 结合 Prompt、Schema、JOIN 提示和 few-shot 生成 SQL |
| 6 | 安全校验 | 禁止危险 SQL，自动补 `LIMIT`，规范格式 |
| 7 | SQL 执行与修复 | 在业务执行库中运行 SQL，失败则调用 LLM 修复并重试 |

### 3.3 节点 1：意图理解

- 输入：用户自然语言问题
- 输出：`intent_json`
- 关键字段：
  - `anchor_tables`
  - `search_queries`
  - `time_range`
  - `filters`
  - `ambiguity`

这一层不直接生成 SQL，而是先把自然语言问题结构化，减少后续 SQL 幻觉。

### 3.4 节点 2：并行检索

项目维护两套向量集合：

| 集合 | 数据来源 | 说明 |
|------|----------|------|
| `mes_schema_embeddings` | `data/mes_knowledge_base.txt` | 表结构知识库 |
| `mes_few_shot_embeddings` | `data/dify_few_shot.txt` | SQL 示例库 |

检索时会把：

- 原始问题
- 意图理解生成的扩展检索词

一起用于召回相关表和示例，提升检索命中率。

### 3.5 节点 3：BFS 图扩展

项目会根据 `data/mes_relation_graph.json` 中维护的关系图做 BFS 扩展：

- 以锚点表为起点
- 沿图关系逐层扩展
- 生成可用表集合
- 生成 `JOIN` 提示文本

相关配置：

```bash
BFS_MAX_HOPS=2
BFS_MAX_TABLES=10
```

这一步的目标不是扩大表范围，而是控制表范围，确保 LLM 只在“可能连得上”的表之间做选择。

### 3.6 节点 4：Schema 组装

从检索召回的大量表结构中，只保留 BFS 扩展后的目标表，减少 Prompt 噪音并降低误用表的概率。

### 3.7 节点 5：SQL 生成

输入信息主要包括：

- 用户问题
- 精简后的 `schema_context`
- BFS 推导的 `join_hints`
- few-shot 示例
- 运行时规则与额外硬约束

Prompt 模板位于：

- `data/dify_sql_prompt.txt`

### 3.8 节点 6：安全校验

当前会阻止以下危险关键词：

```python
DELETE UPDATE DROP TRUNCATE INSERT ALTER CREATE GRANT REVOKE
```

并且会自动处理：

- 去掉 Markdown 代码块包裹
- 若无 `LIMIT` 则自动补 `LIMIT 500`
- 统一补分号

### 3.9 节点 7：执行与修复

生成 SQL 在 `SQL_EXECUTION_DATABASE_URL` 指向的业务库中执行。

如果执行失败：

- 返回错误信息
- 结合当前问题、表结构、JOIN 提示和错误文本调用 LLM 修复
- 最多自动重试 3 次

返回结果中会包含：

- `execution_result`
- `retry_count`
- `request_id`
- `knowledge_version`

---

## 4. 目录结构

```text
mes_graph/
├── .env
├── README.md
├── pyproject.toml
├── public.sql
├── mes联表测试问题清单_含完整SQL.csv
├── temp_batch_e2e_report.json
├── test_e2e.py
├── scripts/
│   ├── harness.py
│   └── run_csv_regression.py
├── data/
│   ├── dify_few_shot.txt
│   ├── dify_sql_prompt.txt
│   ├── mes_knowledge_base.txt
│   ├── mes_relation_graph.json
│   └── harness/
│       ├── cases.json
│       ├── evolved_few_shot.txt
│       └── runtime_rules.json
└── src/
    ├── main.py
    ├── core/
    │   └── config.py
    ├── graph/
    │   ├── nodes.py
    │   ├── state.py
    │   └── workflow.py
    ├── harness/
    │   ├── evolution.py
    │   ├── knowledge.py
    │   ├── online_service.py
    │   ├── repository.py
    │   └── runner.py
    ├── models/
    │   └── schemas.py
    ├── services/
    │   ├── bfs.py
    │   ├── llm.py
    │   └── vector_store.py
    └── utils/
        └── sql_validator.py
```

---

## 5. 环境要求

### 5.1 Python

- Python `>= 3.11`

### 5.2 PostgreSQL

需要可访问的 PostgreSQL 实例，建议：

- 一个 `postgres` 或独立项目库，专门存项目内部表
- 一个 `mes` 业务库，专门存 MES 业务表

### 5.3 pgvector

项目内部库需要启用 `pgvector` 扩展，否则无法写入向量集合。

可在项目内部库中执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 5.4 API Key

需要可用的硅基流动 OpenAI 兼容接口配置：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`

---

## 6. 安装与启动

### 6.1 安装依赖

推荐使用 `uv`：

```bash
uv sync
```

如果当前环境没有把 `uv` 加到系统路径，也可以先保证已有 Python 环境，再使用：

```bash
python -m pip install -U uv
uv sync
```

### 6.2 配置 `.env`

推荐参考如下配置：

```bash
# LLM
LLM_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash
INTENT_MODEL=Qwen/Qwen2.5-7B-Instruct

# Embedding
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_API_KEY=

# Database
DATABASE_URL=postgresql://user:pass@host:5432/mes
PROJECT_DATABASE_URL=postgresql://user:pass@host:5432/postgres
SQL_EXECUTION_DATABASE_URL=postgresql://user:pass@host:5432/mes

# Harness
ENABLE_ONLINE_HARNESS=true
HARNESS_AUTO_INIT_DB=true
HARNESS_REQUEST_LOG_ENABLED=true
HARNESS_RUNTIME_CACHE_TTL_SECONDS=60

# Service
HOST=0.0.0.0
PORT=8000

# BFS / Retrieval
BFS_MAX_HOPS=2
BFS_MAX_TABLES=10
RETRIEVAL_TOP_K=8
FEW_SHOT_TOP_K=3
DEFAULT_LIMIT=500
```

### 6.3 首次启动

推荐命令：

```bash
uv run python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

或者直接：

```bash
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

启动时会自动：

- 初始化向量库
- 编译工作流
- 初始化在线 Harness 表（若启用）

### 6.4 开发模式

```bash
uv run uvicorn src.main:app --reload
```

### 6.5 强制重建向量库

当你修改了表结构知识库或 SQL few-shot 后，可以强制重建：

```bash
uv run python src/main.py --rebuild
```

或者：

```bash
FORCE_REBUILD=true
uv run python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

---

## 7. API 说明

### 7.1 健康检查

```http
GET /health
```

返回示例：

```json
{
  "status": "ok"
}
```

### 7.2 自然语言转 SQL

```http
POST /nl2sql
Content-Type: application/json
```

请求体：

```json
{
  "query": "查询最近一周入库数量最多的前10个物料"
}
```

返回示例：

```json
{
  "query": "查询最近一周入库数量最多的前10个物料",
  "sql": "SELECT ... LIMIT 10;",
  "safe": true,
  "error": "",
  "tables_used": ["t_wms_stock", "t_bd_part"],
  "join_hints": "-- 工单←料号 (hop=1)\nJOIN t_bd_part ON ...",
  "execution_result": {
    "success": true,
    "rows": 10,
    "columns": ["part_name", "total_qty"],
    "preview": []
  },
  "retry_count": 0,
  "request_id": "uuid",
  "knowledge_version": "reviewed-mes_graph-3"
}
```

字段说明：

| 字段 | 说明 |
|------|------|
| `sql` | 最终返回给调用方的 SQL |
| `safe` | 是否通过安全校验 |
| `error` | 错误信息，可能来自安全校验或执行失败 |
| `tables_used` | 工作流最终扩展出的相关表 |
| `join_hints` | 自动构造的 JOIN 提示 |
| `execution_result` | 执行结果，包括列名、预览、错误信息 |
| `retry_count` | 自动修复重试次数 |
| `request_id` | 请求唯一标识 |
| `knowledge_version` | 在线 Harness 命中的知识版本 |

### 7.3 在线 Harness 管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/harness/failure-cases` | 查看失败案例 |
| POST | `/admin/harness/failure-cases/{failure_case_id}/label` | 标注失败案例 |
| POST | `/admin/harness/analyze-failures` | 从失败案例生成候选 |
| GET | `/admin/harness/candidates` | 查看候选规则 |
| POST | `/admin/harness/candidates/{candidate_id}/review` | 审核候选 |
| POST | `/admin/harness/publish` | 发布已审核候选 |

---

## 8. 前端测试页面

服务启动且前端已完成构建后，可以直接访问：

- `http://127.0.0.1:8000/console`

这个页面会把主要接口调用过程直接展示出来，适合研发、测试和产品一起联调 NL2SQL 与在线 Harness。

### 8.1 页面能力

- 输入自然语言问题并调用 `/nl2sql`
- 展示 SQL、安全状态、执行结果、错误信息、知识版本
- 查看失败案例列表 `/admin/harness/failure-cases`
- 查看候选规则列表 `/admin/harness/candidates`
- 直接触发失败分析 `/admin/harness/analyze-failures`
- 直接触发已审核候选发布 `/admin/harness/publish`
- 在底部回放最近一次接口执行记录

### 8.2 前端本地开发

前端工程目录：

- `web/`

本地开发命令：

```bash
cd web
npm install
npm run dev
```

说明：

- Vite 默认端口为 `4173`
- `/health`、`/nl2sql`、`/admin` 已通过代理转发到 `http://127.0.0.1:8000`
- 生产构建使用 `base=/console/`，构建后可直接挂到 FastAPI

### 8.3 构建与发布

```bash
cd web
npm run build
```

构建完成后，FastAPI 会自动读取：

- `web/dist/index.html`
- `web/dist/assets/*`

对应访问路径：

- `/console`
- `/console/assets/*`

### 8.4 使用建议

- 页面顶部展示查询结果、右侧展示 Harness 数据、底部展示接口回放，三块内容同时正常时说明联调已打通
- 若浏览器标签仍显示旧标题，通常是缓存问题，刷新或重新打开 `/console` 即可
- 如果失败案例或候选规则为空，先确认 `ENABLE_ONLINE_HARNESS=true` 且服务已正常启动

---

## 9. Harness 闭环说明

项目支持两种 Harness 运行方式：

### 9.1 本地文件模式

本地模式依赖以下文件：

- `data/harness/cases.json`
- `data/harness/runtime_rules.json`
- `data/harness/evolved_few_shot.txt`

适合离线验证和快速迭代。

### 9.2 在线数据库模式

在线模式启用后，系统会把运行数据写入数据库表：

- `nl2sql_request_log`
- `nl2sql_failure_case`
- `nl2sql_runtime_knowledge`
- `nl2sql_rule_candidate`
- `nl2sql_failure_label`

适合持续积累线上运行数据，并对候选规则做审核发布。

### 9.3 典型闭环流程

1. 服务写入 `nl2sql_request_log`
2. 从失败记录同步出 `nl2sql_failure_case`
3. 分析失败案例生成候选规则
4. 人工审核候选
5. 发布审核通过的规则和 few-shot
6. 新知识在后续请求中生效

### 9.4 Harness CLI

主要脚本：

```bash
python scripts/harness.py --help
```

常用命令：

```bash
# 从 CSV 初始化测试用例
python scripts/harness.py bootstrap-csv

# 运行回归测试
python scripts/harness.py run --base-url http://127.0.0.1:8000 --report temp_batch_e2e_report.json

# 运行后自动进化
python scripts/harness.py run --evolve

# 基于报告生成本地运行时规则
python scripts/harness.py evolve --report temp_batch_e2e_report.json

# 从线上日志直接进化并发布知识
python scripts/harness.py evolve-online --limit 200

# 分析失败案例，生成待审核候选
python scripts/harness.py analyze-failures --limit 200

# 查看失败案例
python scripts/harness.py list-failures --status open --limit 20

# 标注失败案例
python scripts/harness.py label-failure --failure-case-id 1 --correct-sql "SELECT ..." --note "人工修正"

# 查看候选规则
python scripts/harness.py list-candidates --status pending --limit 20

# 审核候选
python scripts/harness.py review-candidate --candidate-id 1 --action approve --note "结构正确，可发布"

# 发布已审核候选
python scripts/harness.py publish-approved --version 2026-06-04-v1
```

### 9.5 CSV 联表回归脚本

项目还提供了单独的 CSV 回放脚本：

```bash
python scripts/run_csv_regression.py
```

它会：

- 读取 `mes联表测试问题清单_含完整SQL.csv`
- 对比标准 SQL 与生成 SQL 的执行情况
- 输出 `temp_batch_e2e_report.json`

---

## 10. 数据文件说明

| 文件 | 说明 |
|------|------|
| `data/mes_knowledge_base.txt` | MES 表结构知识库，按 `---` 分块 |
| `data/dify_few_shot.txt` | SQL 示例知识库 |
| `data/dify_sql_prompt.txt` | SQL 生成 Prompt 模板 |
| `data/mes_relation_graph.json` | 表关系图，用于 BFS 扩展 |
| `data/harness/cases.json` | Harness 用例 |
| `data/harness/runtime_rules.json` | 本地运行时规则 |
| `data/harness/evolved_few_shot.txt` | 本地进化 few-shot |
| `public.sql` | 当前使用的 PostgreSQL DDL / 样例数据文件 |
| `mes联表测试问题清单_含完整SQL.csv` | 联表测试问题清单与标准 SQL |

---

## 11. 开发与维护

### 10.1 代码质量

```bash
uv run ruff check .
uv run ruff format .
uv run mypy src
```

### 10.2 测试

```bash
uv run pytest
```

### 10.3 OpenAPI 文档

启动服务后可访问：

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/redoc`

---

## 12. 常见问题

### 11.1 启动时报 pgvector 相关错误

通常说明项目内部库没有启用 `vector` 扩展，请在 `PROJECT_DATABASE_URL` 指向的库中执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 11.2 SQL 一直查错库

检查以下配置是否正确：

- `PROJECT_DATABASE_URL` 是否指向项目内部库
- `SQL_EXECUTION_DATABASE_URL` 是否指向 MES 业务库

### 11.3 为什么明明生成了 SQL 还返回失败

可能原因：

- SQL 虽然语法通过，但执行时报字段名或 JOIN 错误
- 执行库中缺少相应表或字段
- 安全校验拦截了危险关键字
- 已达到最大重试次数

### 11.4 修改知识库后为什么结果没变化

因为向量集合默认不会重复构建。修改以下文件后，需要强制重建：

- `data/mes_knowledge_base.txt`
- `data/dify_few_shot.txt`

执行：

```bash
uv run python src/main.py --rebuild
```

---

## 13. 推荐上线方式

推荐按以下方式部署：

1. `PROJECT_DATABASE_URL` 指向独立项目库
2. `SQL_EXECUTION_DATABASE_URL` 指向真实 MES 业务库
3. 开启 `ENABLE_ONLINE_HARNESS=true`
4. 开启 `HARNESS_AUTO_INIT_DB=true`
5. 开启 `HARNESS_REQUEST_LOG_ENABLED=true`
6. 定时执行 `analyze-failures`
7. 人工审核候选后执行 `publish-approved`

这样可以保证：

- 项目内部表不会污染业务库
- 联表失败案例可以持续沉淀
- 运行时知识可控发布，不会直接污染线上

---

## 14. 依赖摘要

`pyproject.toml` 当前核心依赖包括：

- `langgraph`
- `langchain`
- `langchain-openai`
- `langchain-postgres`
- `asyncpg`
- `pgvector`
- `fastapi`
- `uvicorn[standard]`
- `pydantic`
- `pydantic-settings`
- `python-dotenv`

开发依赖包括：

- `pytest`
- `ruff`
- `mypy`
