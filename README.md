# MES NL2SQL

基于 `FastAPI + LangGraph + PostgreSQL + pgvector` 的 MES 自然语言转 SQL 服务，支持多轮对话、双库拆分、Harness 数据飞轮闭环。

---

## 1. 项目概览

### 1.1 核心能力

| 能力 | 说明 |
|------|------|
| NL2SQL | 将自然语言问题转换为 PostgreSQL SQL |
| 意图理解 | LLM 提取锚点表、搜索词、时间范围、筛选条件，结构化后再检索 |
| 向量检索 | pgvector 存储表结构 DDL 和 SQL 示例，语义召回相关上下文 |
| BFS 图扩展 | 基于表关系图自动推导可行 JOIN 路径，生成 JOIN 提示 |
| 安全校验 | 关键字黑名单禁止写操作，自动补 LIMIT |
| EXPLAIN 校验 | 节点 7 通过 `EXPLAIN (FORMAT JSON)` 验证 SQL 正确性，不实际执行查询 |
| 自动修复 | 校验失败时 LLM 修复 SQL 并重试（最多 3 次） |
| 多 SQL | 支持一条自然语言拆分为多条子查询，各自独立生成/校验 |
| 分页查询 | `/execute/page` 接口提供实际数据分页查询 |
| 多轮对话 | `/chat/stream` 支持 SSE 流式返回 + thread_id 会话记忆 |
| 在线 Harness | 请求日志 → 失败案例 → 规则候选 → 人工审核 → 发布，形成数据飞轮 |
| 双库拆分 | 项目内部库（向量 + Harness）与业务执行库（MES 表）物理分离 |

### 1.2 适用场景

- MES 业务数据查询：工单、SN 追溯、过站、不良、检验、库存、设备、料号、BOM 等
- 联表查询自动推导 JOIN 路径
- 作为智能问答 / 报表平台 / 数据助手的后端
- 持续沉淀失败案例并迭代运行时规则

### 1.3 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| Web 框架 | FastAPI | REST + SSE 流式 |
| Agent 编排 | LangGraph | 7 节点状态图，含条件分支与重试回路 |
| LLM（SQL 生成/修复） | DeepSeek 系列 | 默认 `deepseek-v4-flash` |
| LLM（意图理解） | DeepSeek 系列 | 默认 `deepseek-v4-flash`，可通过 `INTENT_MODEL` 独立配置 |
| Embedding | BAAI/bge-large-zh-v1.5 | 表结构与示例检索 |
| 向量库 | pgvector | 内嵌于 PostgreSQL |
| 数据库驱动 | psycopg / asyncpg | 同步执行 + 异步向量操作 |
| 配置管理 | pydantic-settings | .env 统一加载 |
| 包管理 | uv | 依赖管理与运行 |

---

## 2. 系统架构

### 2.1 整体架构图

```
┌──────────────┐     ┌──────────────────────────────────────┐
│   前端页面    │     │           FastAPI 服务                │
│  /console    │────▶│  /nl2sql    /chat/stream  /execute/page│
│  (React)     │     │  /admin/harness/*  /health            │
└──────────────┘     └──────────┬───────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │     LangGraph 工作流    │
                    │  intent → retrieval    │
                    │    → bfs → schema      │
                    │    → sql_gen → safety  │
                    │    → execute(EXPLAIN)  │
                    └───────────┬───────────┘
                                │
            ┌───────────────────┼───────────────────┐
            ▼                   ▼                   ▼
   ┌────────────────┐  ┌──────────────┐  ┌─────────────────┐
   │ 项目内部库       │  │  业务执行库   │  │  LLM API        │
   │ (PostgreSQL)    │  │ (PostgreSQL) │  │ (硅基流动/OpenAI) │
   │ - pgvector      │  │ - MES 业务表 │  │                 │
   │ - Harness 表    │  │ EXPLAIN 在此 │  │                 │
   │ - 运行时知识    │  │ 数据查询在此  │  │                 │
   └────────────────┘  └──────────────┘  └─────────────────┘
```

### 2.2 双库架构

| 连接 | 配置项 | 用途 |
|------|--------|------|
| 项目内部库 | `PROJECT_DATABASE_URL` | pgvector 向量集合、Harness 运行表（`nl2sql_*`）、运行时知识 |
| 业务执行库 | `SQL_EXECUTION_DATABASE_URL` | MES 业务表，EXPLAIN 校验和数据查询在此 |
| 兼容兜底 | `DATABASE_URL` | 未配置上述两项时的回退连接 |

推荐配置：

```bash
DATABASE_URL=postgresql://user:pass@host:5432/mes
PROJECT_DATABASE_URL=postgresql://user:pass@host:5432/postgres
SQL_EXECUTION_DATABASE_URL=postgresql://user:pass@host:5432/mes
```

### 2.3 启动初始化

服务启动时（`lifespan` 阶段）自动执行：

1. 初始化表结构向量库 `mes_schema_embeddings`
2. 初始化示例向量库 `mes_few_shot_embeddings`
3. 编译 LangGraph 工作流
4. 若启用在线 Harness，自动创建 `nl2sql_*` 系列表

向量库已有数据时仅做连通性检查，跳过重复写入。

---

## 3. 工作流详解

### 3.1 整体流程

```
用户问题
  → 节点1 意图理解 (LLM)
  → 节点2 并行检索 (pgvector)
  → 节点3 BFS 图扩展 (代码逻辑)
  → 节点4 Schema 组装 (代码逻辑)
  → 节点5 SQL 生成 (LLM)
  → 节点6 安全校验 (代码逻辑)
  → 节点7 EXPLAIN 校验与修复 (LLM + 重试回路)
  → 返回结果
```

节点 7 校验失败时触发 LLM 修复，通过条件边回到自身重试（最多 3 次）。

### 3.2 节点 1：意图理解

- **输入**：用户自然语言问题 + 运行时规则约束
- **输出**：`intent_json`（锚点表、搜索词、时间范围、筛选条件、歧义标注）+ `sub_queries`（多 SQL 时拆分）
- **目的**：不直接生成 SQL，先结构化问题，减少后续 SQL 幻觉

关键字段：

| 字段 | 说明 |
|------|------|
| `anchor_tables` | 锚点表，BFS 扩展的起点 |
| `search_queries` | 扩展检索词，提升向量召回命中率 |
| `time_range` | 时间过滤条件 |
| `filters` | 业务维度过滤 |
| `ambiguity` | 歧义标注与消歧建议 |

多 SQL 模式：当意图理解判断一个问题需要多条独立 SQL 回答时，输出 `sub_queries` 列表，后续节点逐条处理。

### 3.3 节点 2：并行检索

维护两套 pgvector 向量集合：

| 集合 | 数据源 | 内容 |
|------|--------|------|
| `mes_schema_embeddings` | `data/mes_knowledge_base.txt` | MES 表结构 DDL（按 `---` 分块） |
| `mes_few_shot_embeddings` | `data/dify_few_shot.txt` | SQL 示例（问题-SQL 对） |

检索策略：用户原始问题 + 意图理解扩展词 → Embedding → 语义召回 Top-K 文档。

配置项：

```bash
RETRIEVAL_TOP_K=8          # 表结构召回数
FEW_SHOT_TOP_K=3           # SQL 示例召回数
RETRIEVAL_SIMILARITY_THRESHOLD=0.55   # 相似度阈值
```

### 3.4 节点 3：BFS 图扩展

基于 `data/mes_relation_graph.json` 中的表关系图：

- 以锚点表为起点，沿 JOIN 边做 BFS 扩展
- 域感知：`t_pd_`（生产）、`t_qm_`（质量）、`t_wms_`（仓库）、`t_ems_`（设备）、`t_bd_`（基础数据）
- 跨域 JOIN 标记置信度（low / medium / high）
- 生成可用的 JOIN 提示文本

配置项：

```bash
BFS_MAX_HOPS=2              # 最大跳数
BFS_MAX_TABLES=10           # 最大表数
```

### 3.5 节点 4：Schema 组装

从检索召回的大量表结构中，只保留 BFS 扩展目标表的 DDL。减少 Prompt 噪音，降低 LLM 误用无关表的概率。

### 3.6 节点 5：SQL 生成

LLM 综合以下信息生成 SQL：

- 用户原始问题
- 精简后的 `schema_context`（目标表 DDL）
- BFS 推导的 `join_hints`
- 检索到的 few-shot SQL 示例
- 运行时规则（Harness 产出）
- 意图理解的结构化约束

Prompt 模板：`data/dify_sql_prompt.txt`

生成后还有一层约束检查（`_build_sql_constraint_feedback`）：验证 SQL 是否包含必备的主表、关联表和 JOIN，不满足则作为反馈送回 LLM 重写。

### 3.7 节点 6：安全校验

实现：[src/utils/sql_validator.py](src/utils/sql_validator.py)

三步策略：

1. **关键字黑名单**：禁止 `DELETE / UPDATE / DROP / TRUNCATE / INSERT / ALTER / CREATE / GRANT / REVOKE`
2. **Markdown 清理**：去除 LLM 可能输出的 ` ```sql ` 围栏
3. **LIMIT 强制**：若无 LIMIT 则追加 `LIMIT {DEFAULT_LIMIT}`（默认 500）

校验结果：`{"safe": bool, "final_sql": str, "error": str}`

### 3.8 节点 7：EXPLAIN 校验与修复

实现：[src/graph/nodes.py](src/graph/nodes.py) `node_7_execute_and_repair()` + `_explain_sql()`

**不再实际执行查询**，而是通过 PostgreSQL 的 `EXPLAIN (FORMAT JSON)` 验证 SQL 正确性：

- 能捕获：表/列不存在、JOIN 语法错误、类型不匹配等
- 零数据扫描成本，校验即时返回
- 实际数据查询由独立的 `/execute/page` 接口处理

**修复流程**：

```
EXPLAIN 失败 → LLM 修复 SQL → 重新 EXPLAIN → 成功/继续重试（最多 3 次）
```

若错误匹配 `"column does not exist"`，会查询 `information_schema.columns` 获取真实列名作为修复提示。

**返回字段**：

| 字段 | 说明 |
|------|------|
| `success` | EXPLAIN 是否通过 |
| `explain_plan` | PostgreSQL 查询计划（JSON） |
| `error` | 校验失败时的数据库错误信息 |

**多 SQL 模式**：每条子 SQL 独立 EXPLAIN + 内联重试，不触发外层工作流重试回路。

---

## 4. API 说明

### 4.1 接口总览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/` | 重定向到 `/console` 或 `/docs` |
| POST | `/nl2sql` | 自然语言转 SQL（同步） |
| POST | `/chat/stream` | 对话式 NL2SQL（SSE 流式），支持多轮记忆 |
| POST | `/execute/page` | 分页执行 SQL（实际数据查询） |
| GET | `/admin/harness/failure-cases` | 查看失败案例 |
| POST | `/admin/harness/failure-cases/{id}/label` | 标注失败案例 |
| POST | `/admin/harness/analyze-failures` | 分析失败案例生成候选规则 |
| POST | `/admin/harness/auto-label-failures` | LLM 自动标注失败案例 |
| POST | `/admin/harness/evolve-online` | 从线上日志进化运行时知识 |
| GET | `/admin/harness/candidates` | 查看候选规则 |
| POST | `/admin/harness/candidates/{id}/review` | 审核候选规则 |
| POST | `/admin/harness/publish` | 发布已审核候选 |
| POST | `/admin/harness/feedback` | 用户点赞/点踩反馈 |
| GET | `/console` | 前端测试页面 |
| GET | `/docs` | OpenAPI 文档 |

### 4.2 POST /nl2sql

请求：

```json
{
  "query": "查询最近一周入库数量最多的前10个物料",
  "thread_id": "optional-session-id"
}
```

响应：

```json
{
  "query": "查询最近一周入库数量最多的前10个物料",
  "sql": "SELECT ... LIMIT 10;",
  "sqls": ["SELECT ... LIMIT 10;"],
  "safe": true,
  "error": "",
  "tables_used": ["t_wms_stock", "t_bd_part"],
  "join_hints": "JOIN t_bd_part ON ...",
  "execution_result": {
    "success": true,
    "explain_plan": { "Plan": { ... } }
  },
  "execution_results": [{ "success": true, "explain_plan": { ... } }],
  "retry_count": 0,
  "request_id": "uuid",
  "knowledge_version": "2026-06-04-v1",
  "multi_sql": false,
  "sub_queries": []
}
```

### 4.3 POST /chat/stream

SSE 事件流格式：

```
data: {"node":"intent","status":"progress","thread_id":"...","data":{...}}
data: {"node":"retrieval","status":"progress","thread_id":"...","data":{...}}
...
data: {"node":"done","status":"complete","thread_id":"...","request_id":"...","data":{...}}
```

每个节点完成后推送一次进度事件。`done` 事件携带完整结果（含 `execution_results`、`final_sqls`、`multi_sql`、`sub_queries`）。

多轮对话：通过 `thread_id` 维护会话历史（最多保留最近 10 轮），历史只存摘要不存完整数据。

### 4.4 POST /execute/page

分页执行 SQL（实际数据查询入口）：

请求：

```json
{
  "sql": "SELECT * FROM t_pd_work_order",
  "page": 1,
  "page_size": 20
}
```

响应：

```json
{
  "success": true,
  "total_rows": 1523,
  "page": 1,
  "page_size": 20,
  "total_pages": 77,
  "columns": ["wo_id", "sn", "create_time", ...],
  "rows": [{ "wo_id": 1, "sn": "DAH01", ... }, ...],
  "error": ""
}
```

---

## 5. 目录结构

```
mes_graph/
├── .env                          # 环境变量配置
├── .python-version               # Python 版本锁定
├── pyproject.toml                # 项目元数据与依赖
├── uv.lock                       # 依赖锁文件
├── README.md
│
├── src/                          # Python 源代码
│   ├── main.py                   # FastAPI 入口，路由定义，生命周期管理
│   ├── core/
│   │   └── config.py             # pydantic-settings 配置（环境变量映射）
│   ├── graph/                    # LangGraph 工作流
│   │   ├── state.py              # GraphState 类型定义（节点间数据流转）
│   │   ├── nodes.py              # 7 个节点实现 + EXPLAIN / 分页执行
│   │   └── workflow.py           # 工作流组装 + 条件路由
│   ├── models/
│   │   └── schemas.py            # Pydantic 请求/响应模型
│   ├── services/                 # 服务层
│   │   ├── llm.py                # LLM 客户端初始化
│   │   ├── bfs.py                # BFS 图扩展（域感知 + JOIN 路径推导）
│   │   └── vector_store.py       # pgvector 向量库构建与查询
│   ├── harness/                  # Harness 数据飞轮
│   │   ├── repository.py         # 数据库 CRUD（nl2sql_* 表）
│   │   ├── runner.py             # 回归测试执行器
│   │   ├── evolution.py          # 规则进化（从失败中学习）
│   │   ├── knowledge.py          # 运行时知识加载（规则 + 进化 few-shot）
│   │   ├── online_service.py     # 在线 Harness 服务编排
│   │   └── llm_labeler.py        # LLM 自动标注
│   └── utils/
│       └── sql_validator.py      # SQL 安全校验（关键字黑名单 + LIMIT）
│
├── data/                         # 数据文件
│   ├── mes_knowledge_base.txt    # MES 表结构知识库（DDL，按 --- 分块）
│   ├── dify_few_shot.txt         # SQL 示例库（问题-SQL 对）
│   ├── dify_sql_prompt.txt       # SQL 生成 Prompt 模板
│   ├── mes_relation_graph.json   # 表关系图（用于 BFS 扩展）
│   └── harness/
│       ├── cases.json            # 本地测试用例
│       ├── runtime_rules.json    # 本地运行时规则
│       └── evolved_few_shot.txt  # 本地进化 few-shot
│
├── scripts/                      # 运维脚本
│   ├── harness.py                # Harness CLI（用例管理、回归、进化、审核）
│   └── run_csv_regression.py     # CSV 回归测试脚本
│
├── web/                          # React 前端（Vite + TypeScript + Tailwind）
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── Home.tsx          # NL2SQL 查询页面
│   │   │   ├── Chat.tsx          # 对话式查询页面
│   │   │   └── Harness.tsx       # Harness 管理页面
│   │   ├── components/           # 通用组件
│   │   ├── lib/
│   │   │   ├── api.ts            # API 调用封装
│   │   │   ├── stream.ts         # SSE 流处理
│   │   │   └── utils.ts
│   │   └── types.ts              # TypeScript 类型定义
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
│
├── files/                        # 参考文件（非运行时依赖）
│   ├── dify_code_node_v2.py
│   ├── dify_prompt_v2.txt
│   └── workflow_v2.md
│
├── execute_public_sql.py         # public.sql 批量执行脚本
├── public.sql                    # MES 业务表 DDL 样例
├── mes联表测试问题清单_含完整SQL.csv  # 联表回归测试用例
├── mes数据库.txt                  # 数据库表结构参考
└── mes数据库关联关系.json          # 表关联关系参考
```

---

## 6. 环境配置

### 6.1 环境要求

- Python >= 3.11
- PostgreSQL（需启用 pgvector 扩展）
- 硅基流动（或 OpenAI 兼容）API Key

### 6.2 完整配置项

```bash
# ── LLM ──────────────────────────────────
LLM_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash        # SQL 生成/修复用
INTENT_MODEL=Qwen/Qwen2.5-7B-Instruct           # 意图理解用

# ── Embedding ────────────────────────────
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_API_KEY=                              # 空则复用 OPENAI_API_KEY

# ── Database ─────────────────────────────
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/mes
PROJECT_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/postgres
SQL_EXECUTION_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/mes

# ── Harness ──────────────────────────────
ENABLE_ONLINE_HARNESS=true                      # 启用在线 Harness
HARNESS_AUTO_INIT_DB=true                       # 自动建表
HARNESS_REQUEST_LOG_ENABLED=true                # 记录请求日志
HARNESS_RUNTIME_CACHE_TTL_SECONDS=60            # 规则缓存 TTL

# ── Service ──────────────────────────────
HOST=0.0.0.0
PORT=8000

# ── BFS ──────────────────────────────────
BFS_MAX_HOPS=2                                  # BFS 最大跳数
BFS_MAX_TABLES=10                               # BFS 最大表数

# ── Retrieval ────────────────────────────
RETRIEVAL_TOP_K=8                               # 表结构召回数
FEW_SHOT_TOP_K=3                                # SQL 示例召回数
RETRIEVAL_SIMILARITY_THRESHOLD=0.55              # 相似度阈值
DEFAULT_LIMIT=500                               # 安全校验默认 LIMIT
```

---

## 7. 安装与启动

### 7.1 安装依赖

```bash
uv sync --dev
```

### 7.2 创建 pgvector 扩展

在项目内部库中执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 7.3 启动服务

```bash
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

开发模式（热重载）：

```bash
uv run uvicorn src.main:app --reload
```

### 7.4 强制重建向量库

修改知识库文件后：

```bash
uv run python src/main.py --rebuild
```

或设置环境变量：

```bash
FORCE_REBUILD=true uv run uvicorn src.main:app
```

### 7.5 前端开发

```bash
cd web
npm install
npm run dev         # 开发模式，端口 4173
npm run build       # 生产构建，输出到 web/dist/
```

---

## 8. Harness 数据飞轮

### 8.1 设计理念

```
用户查询 → NL2SQL → 执行结果
                ↓ (失败时)
          失败案例入库
                ↓
         分析生成候选规则
                ↓
         人工审核 + 发布
                ↓
         运行时规则注入 Prompt
                ↓
         下次查询命中更准
```

### 8.2 数据库表

启用在线 Harness 后，项目内部库自动创建以下表：

| 表名 | 用途 |
|------|------|
| `nl2sql_request_log` | 每次 NL2SQL 请求的完整日志 |
| `nl2sql_failure_case` | 执行失败的案例（待标注） |
| `nl2sql_failure_label` | 人工标注的正确 SQL |
| `nl2sql_rule_candidate` | 从失败中提取的候选规则（待审核） |
| `nl2sql_runtime_knowledge` | 已发布的运行时知识（版本化） |

### 8.3 Harness CLI

```bash
# 从 CSV 初始化测试用例
python scripts/harness.py bootstrap-csv

# 运行回归测试
python scripts/harness.py run --base-url http://127.0.0.1:8000 --report report.json

# 运行并自动进化
python scripts/harness.py run --evolve

# 基于报告生成本地规则
python scripts/harness.py evolve --report report.json

# 从线上日志进化并发布知识
python scripts/harness.py evolve-online --limit 200

# 分析失败案例生成候选
python scripts/harness.py analyze-failures --limit 200

# 查看失败案例
python scripts/harness.py list-failures --status open --limit 20

# 标注失败案例
python scripts/harness.py label-failure --failure-case-id 1 --correct-sql "SELECT ..."

# 审核候选
python scripts/harness.py review-candidate --candidate-id 1 --action approve

# 发布已审核候选
python scripts/harness.py publish-approved --version 2026-06-04-v1
```

---

## 9. 代码质量

```bash
uv run ruff check --fix .    # Lint + 自动修复
uv run ruff format .         # 格式化
uv run mypy src/             # 类型检查
uv run pytest                # 运行测试
```

---

## 10. 常见问题

### 启动报 pgvector 错误

项目内部库未启用 vector 扩展：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### SQL 一直查错库

检查：

- `PROJECT_DATABASE_URL` 是否指向项目内部库
- `SQL_EXECUTION_DATABASE_URL` 是否指向 MES 业务库

### 修改知识库后结果没变化

向量集合默认不重复构建。修改 `data/mes_knowledge_base.txt` 或 `data/dify_few_shot.txt` 后需要：

```bash
uv run python src/main.py --rebuild
```

### SQL 校验失败但语法看起来正确

可能原因：

- SQL 中误用了危险关键字作为表名或列名（黑名单是词边界匹配）
- 表/列在业务执行库中实际不存在
- EXPLAIN 校验会给出具体数据库错误信息

---

## 11. 推荐上线方式

1. `PROJECT_DATABASE_URL` 指向独立项目库
2. `SQL_EXECUTION_DATABASE_URL` 指向 MES 业务库
3. 开启 `ENABLE_ONLINE_HARNESS=true`
4. 开启 `HARNESS_AUTO_INIT_DB=true` 和 `HARNESS_REQUEST_LOG_ENABLED=true`
5. 定时执行 `analyze-failures`
6. 人工审核候选后 `publish-approved`
