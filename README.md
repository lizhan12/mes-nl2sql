# MES NL2SQL

基于 `FastAPI + LangGraph + Neo4j + PostgreSQL + pgvector` 的 MES 自然语言转 SQL 查询服务，支持多轮对话、知识库管理、Harness 数据飞轮闭环。

---

## 1. 项目概览

### 1.1 核心能力

| 能力 | 说明 |
|------|------|
| NL2SQL | 将自然语言问题转换为 PostgreSQL SQL |
| 意图理解 | LLM 提取锚点表、搜索词、时间范围、筛选条件，结构化后再检索 |
| 4 层知识检索 | 表结构 DDL + SQL 示例 + 运行时规则 + 进化示例，多层次语义召回 |
| BFS 图扩展 | 基于 Neo4j 表关系图自动推导可行 JOIN 路径，域感知 + 置信度标注 |
| 安全校验 | 关键字黑名单禁止写操作，自动补 LIMIT |
| EXPLAIN 校验 | 通过 `EXPLAIN (FORMAT JSON)` 验证 SQL 正确性，零数据扫描成本 |
| 自动修复 | 校验失败时 LLM 修复 SQL 并重试（最多 3 次） |
| 多 SQL | 支持一条自然语言拆分为多条子查询，各自独立生成/校验 |
| 多轮对话 | `/chat/stream` 支持 SSE 流式返回 + thread_id 会话记忆 |
| 知识库管理 | 表结构 CRUD、LLM 抽取、批量导入、字段剪裁、Neo4j 同步 |
| 关系图管理 | Neo4j 表关系边增删改查，vis-network 可视化 |
| Harness 数据飞轮 | 请求日志 → 失败案例 → LLM 自动标注 → 候选规则 → 人工审核 → 发布，系统持续进化 |
| 用户与认证 | JWT 登录、用户增删改查、角色权限 |
| Trace 追踪 | 全链路节点耗时统计 (P50/P95/P99)、会话级 trace 查看 |
| 双库隔离 | 项目内部库（向量 + Harness）与业务执行库（MES 表）物理分离 |

### 1.2 适用场景

- MES 业务数据查询：工单、SN 追溯、过站、不良、检验、库存、设备、料号、BOM 等
- 联表查询自动推导 JOIN 路径（380+ 张表）
- 作为智能问答 / 报表平台 / 数据助手的后端
- 持续沉淀失败案例并迭代运行时规则

### 1.3 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| Web 框架 | FastAPI | REST + SSE 流式 |
| Agent 编排 | LangGraph | 7 节点状态图，含条件分支与重试回路 |
| LLM | DeepSeek 系列 | 默认 `deepseek-v4-flash` |
| Embedding | BAAI/bge-large-zh-v1.5 | 知识检索与向量存储 |
| 向量库 | pgvector | 内嵌于 PostgreSQL |
| 图数据库 | Neo4j | 表关系图存储、向量索引、Harness 知识索引 |
| 数据库驱动 | psycopg / asyncpg / neo4j | 同步 + 异步操作 |
| 配置管理 | pydantic-settings | .env 统一加载 |
| 包管理 | uv | 依赖管理与运行 |
| 前端 | React 18 + Vite + TypeScript + Tailwind CSS | SPA 管理界面 |
| 图可视化 | vis-network | 表关系图交互渲染 |

---

## 2. 系统架构

### 2.1 整体架构图

```
┌──────────────┐     ┌──────────────────────────────────────┐
│   前端页面    │     │           FastAPI 服务                │
│  /console    │────▶│  /nl2sql  /chat/stream  /health       │
│  (React)     │     │  /api/knowledge/*  /api/trace/*       │
└──────────────┘     │  /api/graph/*  /admin/harness/*       │
                     │  /auth/*  /api/users/*               │
                     └──────────┬───────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │     LangGraph 工作流    │
                    │  intent → retrieval    │
                    │    → bfs → schema      │
                    │    → sql_gen → safety  │
                    │    → execute(EXPLAIN)  │
                    └───────────┬───────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐
│   Neo4j      │  │  项目内部库       │  │  业务执行库       │
│ - 表关系图   │  │ (PostgreSQL)      │  │ (PostgreSQL)      │
│ - 向量索引   │  │ - pgvector        │  │ - MES 业务表      │
│ - 知识索引   │  │ - Harness 表      │  │ - EXPLAIN 校验    │
└──────────────┘  │ - 运行时知识      │  │ - 数据查询        │
                  └──────────────────┘  └──────────────────┘
                            │
                    ┌───────▼───────┐
                    │   LLM API     │
                    │ (DeepSeek)    │
                    └───────────────┘
```

### 2.2 三库架构

| 连接 | 配置项 | 用途 |
|------|--------|------|
| Neo4j 图库 | `NEO4J_URI` | 表关系图存储、4 类向量索引、Harness 知识索引 |
| 项目内部库 | `PROJECT_DATABASE_URL` | pgvector 向量集合、Harness 运行表（`nl2sql_*`）、用户表 |
| 业务执行库 | `SQL_EXECUTION_DATABASE_URL` | MES 业务表，EXPLAIN 校验和数据查询在此 |
| 兼容兜底 | `DATABASE_URL` | 未配置上述两项时的回退连接 |

---

## 3. 工作流详解

### 3.1 整体流程 (7 节点 Pipeline)

```
用户问题
  → 节点1 意图理解 (LLM)
  → 节点2 并行检索 (Neo4j 向量索引)
  → 节点3 BFS 图扩展 (Neo4j 图 + 代码逻辑)
  → 节点4 Schema 组装 (代码逻辑)
  → 节点5 SQL 生成 (LLM + FewShot + 运行时规则)
  → 节点6 安全校验 (代码逻辑)
  → 节点7 EXPLAIN 校验与修复 (LLM + 重试回路)
  → 返回结果
```

### 3.2 节点 1：意图理解

- **输入**：用户自然语言问题 + 运行时规则约束
- **输出**：`intent_json`（锚点表、搜索词、时间范围、筛选条件、歧义标注）+ `sub_queries`
- **目的**：不直接生成 SQL，先结构化问题，减少后续 SQL 幻觉

### 3.3 节点 2：并行检索

在 Neo4j 中维护 4 类向量索引，并行检索：

| 索引 | 数据源 | 内容 |
|------|--------|------|
| 表结构索引 | `data/mes_knowledge_base.txt` | MES 表 DDL 与业务定义 |
| SQL 示例索引 | `data/dify_few_shot.txt` | 问题-SQL 对 |
| 运行时规则索引 | Harness 发布产出 | 失败案例沉淀的规则 |
| 进化示例索引 | Harness 进化产出 | 从失败中学习的 FewShot |

### 3.4 节点 3：BFS 图扩展

基于 Neo4j 中的表关系图：

- 以锚点表为起点，沿 JOIN 边做 BFS 扩展
- 域感知：`t_pd_`（生产）、`t_qm_`（质量）、`t_wms_`（仓库）、`t_ems_`（设备）、`t_bd_`（基础数据）
- 跨域 JOIN 标记置信度（low / medium / high）
- 生成可用的 JOIN 提示文本

配置项：`BFS_MAX_HOPS=2`、`BFS_MAX_TABLES=10`

### 3.5 节点 5：SQL 生成

LLM 综合以下信息生成 SQL：

- 用户原始问题
- 精简后的 `schema_context`（目标表 DDL）
- BFS 推导的 `join_hints`
- 检索到的 FewShot SQL 示例（含进化 FewShot）
- 运行时规则（Harness 产出）
- 意图理解的结构化约束

生成后还有约束检查（`_build_sql_constraint_feedback`）：验证 SQL 是否包含必备的主表、关联表和 JOIN，不满足则反馈回 LLM 重写。

### 3.6 节点 7：EXPLAIN 校验与修复

通过 PostgreSQL 的 `EXPLAIN (FORMAT JSON)` 验证 SQL 正确性（不实际执行查询）。失败则 LLM 修复后重试（最多 3 次）。若错误匹配 `"column does not exist"`，会查询 `information_schema.columns` 获取真实列名作为修复提示。

---

## 4. API 说明

### 4.1 系统与认证

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/` | 重定向到 `/console` 或 `/docs` |
| GET | `/console` | 前端管理界面入口 |
| POST | `/auth/login` | 用户登录，返回 JWT token |
| POST | `/auth/logout` | 用户登出 |
| GET | `/auth/me` | 获取当前登录用户信息 |
| GET | `/docs` | OpenAPI 文档 |

### 4.2 NL2SQL 查询

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/nl2sql` | 自然语言转 SQL（同步） |
| POST | `/chat/stream` | 对话式 NL2SQL（SSE 流式，多轮记忆） |

### 4.3 关系图管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/graph` | 获取完整表关系图数据 |
| GET | `/api/graph/version` | 获取图版本号 |
| POST | `/api/graph/sync` | 从本地 JSON 同步到 Neo4j |
| GET | `/api/graph/edges` | 列表查询关系边 |
| GET | `/api/graph/edges/detail` | 获取单条关系边详情 |
| POST | `/api/graph/edges` | 添加关系边 |
| PUT | `/api/graph/edges` | 更新关系边 |
| DELETE | `/api/graph/edges` | 删除关系边 |

### 4.4 知识库管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/knowledge/tables` | 列出知识库中所有表 |
| POST | `/api/knowledge/tables/extract` | LLM 从原始文本抽取表结构 |
| POST | `/api/knowledge/tables/batch-add` | 批量添加表定义和关联关系 |
| GET | `/api/knowledge/tables/{table_name}` | 获取单张表完整详情 |
| PUT | `/api/knowledge/tables/{table_name}` | 更新表定义 |
| GET | `/api/knowledge/tables/{table_name}/columns` | 从数据库获取真实列名 |
| DELETE | `/api/knowledge/tables/{table_name}` | 删除表定义 |
| POST | `/api/knowledge/search` | 知识库检索（表结构+SQL示例+字段+规则+进化示例） |
| POST | `/api/knowledge/sync-from-neo4j` | Neo4j 同步回本地文件 |

### 4.5 FewShot 管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/knowledge/few-shots` | 列出所有 FewShot 示例 |
| POST | `/api/knowledge/few-shots` | 创建 FewShot 示例 |
| PUT | `/api/knowledge/few-shots/{id}` | 更新 FewShot 示例 |
| DELETE | `/api/knowledge/few-shots/{id}` | 删除 FewShot 示例 |
| PATCH | `/api/knowledge/few-shots/{id}/enabled` | 启用/禁用 FewShot |

### 4.6 进化 FewShot 管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/knowledge/evolved-few-shots` | 列出所有进化 FewShot |
| POST | `/api/knowledge/evolved-few-shots` | 创建进化 FewShot |
| PUT | `/api/knowledge/evolved-few-shots/{id}` | 更新进化 FewShot |
| DELETE | `/api/knowledge/evolved-few-shots/{id}` | 删除进化 FewShot |
| PATCH | `/api/knowledge/evolved-few-shots/{id}/enabled` | 启用/禁用进化 FewShot |

### 4.7 运行时规则管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/knowledge/runtime-rules` | 列出所有运行时规则 |
| POST | `/api/knowledge/runtime-rules` | 创建运行时规则 |
| PUT | `/api/knowledge/runtime-rules/{normalized_question}` | 更新运行时规则 |
| DELETE | `/api/knowledge/runtime-rules/{normalized_question}` | 删除运行时规则 |
| PATCH | `/api/knowledge/runtime-rules/{normalized_question}/enabled` | 启用/禁用运行时规则 |

### 4.8 Harness 数据飞轮 (Admin)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/harness/feedback` | 查看用户点赞/点踩反馈 |
| POST | `/admin/harness/feedback` | 提交点赞/点踩反馈 |
| GET | `/admin/harness/failure-cases` | 查看失败案例 |
| POST | `/admin/harness/failure-cases/{id}/label` | 人工标注失败案例 |
| DELETE | `/admin/harness/failure-cases/{id}` | 删除失败案例 |
| POST | `/admin/harness/analyze-failures` | 分析失败案例生成候选规则 |
| POST | `/admin/harness/auto-label-failures` | LLM 自动标注 + 多维度评估 |
| POST | `/admin/harness/evolve-online` | 从线上日志进化运行时知识 |
| GET | `/admin/harness/candidates` | 查看候选规则 |
| POST | `/admin/harness/candidates/{id}/review` | 审核候选规则（approve/reject） |
| DELETE | `/admin/harness/candidates/{id}` | 删除候选规则 |
| POST | `/admin/harness/pre-publish-check` | 发布前去重检查 |
| POST | `/admin/harness/publish` | 发布已审核候选规则 |

### 4.9 Trace 追踪

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/trace/recent` | 获取最近的 trace 摘要列表 |
| GET | `/api/trace/stats` | 获取各节点 P50/P95/P99 耗时统计 |
| GET | `/api/trace/thread/{thread_id}` | 获取整个会话所有 trace spans |
| GET | `/api/trace/{trace_id}` | 获取单次请求所有 trace spans |

### 4.10 用户管理 (Admin)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/users` | 分页查询用户列表 |
| POST | `/api/users` | 创建用户 |
| PUT | `/api/users/{user_id}` | 更新用户信息 |
| POST | `/api/users/{user_id}/reset-password` | 重置用户密码 |
| DELETE | `/api/users/{user_id}` | 删除用户 |

---

## 5. 前端页面

基于 React 18 + Vite + TypeScript + Tailwind CSS，路由 basename=`/console`。

| 路由 | 页面 | 功能 |
|------|------|------|
| `/login` | LoginPage | 登录页（无需认证） |
| `/` | Home | **NL2SQL 查询主页**：输入自然语言 → 生成 SQL + EXPLAIN 结果，预设查询示例，活动日志，Harness 概览 |
| `/graph` | GraphPage | **表关系图可视化**：vis-network 渲染 MES 表间 JOIN 关系，支持搜索、边增删改查 |
| `/trace` | TracePage | **Trace 追踪**：查看请求 trace 链路、各节点耗时统计 (P50/P95/P99) |
| `/knowledge` | KnowledgePage | **知识库管理**：表结构 CRUD、LLM 抽取、批量导入、字段剪裁 |
| `/knowledge-search` | KnowledgeSearchPage | **知识库检索**：向量检索表结构/SQL 示例/字段/运行时规则/进化示例 |
| `/few-shot` | FewShotManagement | **FewShot 管理**：SQL 示例及进化示例的增删改查和启用/禁用 |
| `/rule` | RuleManagement | **运行时规则管理**：运行时规则的增删改查和启用/禁用 |
| `/harness` | Harness | **Harness 管理 (Admin)**：失败案例查看/标注、候选规则审核/发布、线上进化 |
| `/users` | UserManagement | **用户管理 (Admin)**：用户增删改查、密码重置 |

---

## 6. 目录结构

```
mes_graph/
├── .env                              # 环境变量配置
├── .python-version                   # Python 版本锁定
├── pyproject.toml                    # 项目元数据与依赖
├── uv.lock                           # 依赖锁文件
├── README.md
│
├── src/                              # Python 源代码
│   ├── main.py                       # FastAPI 入口，路由注册，SPA 静态文件服务
│   ├── core/
│   │   └── config.py                 # pydantic-settings 配置（环境变量映射）
│   ├── graph/                        # LangGraph 工作流
│   │   ├── state.py                  # GraphState 类型定义
│   │   ├── nodes.py                  # 7 个节点实现 + EXPLAIN / 多SQL 处理
│   │   └── workflow.py               # 工作流组装 + 条件路由
│   ├── api/                          # API 路由层
│   │   ├── auth.py                   # 登录/登出/获取用户
│   │   ├── users.py                  # 用户管理 CRUD
│   │   ├── workflow.py               # NL2SQL 查询接口
│   │   ├── graph.py                  # 关系图管理接口
│   │   ├── knowledge.py              # 知识库管理接口
│   │   ├── knowledge_few_shots.py    # FewShot/进化FewShot 管理接口
│   │   ├── knowledge_runtime_rules.py# 运行时规则管理接口
│   │   ├── harness.py                # Harness 数据飞轮接口
│   │   └── trace.py                  # Trace 追踪接口
│   ├── models/
│   │   └── schemas.py                # Pydantic 请求/响应模型
│   ├── services/                     # 服务层
│   │   ├── llm.py                    # LLM 客户端初始化
│   │   ├── bfs.py                    # BFS 图扩展（域感知 + JOIN 路径推导）
│   │   ├── vector_store.py           # pgvector 向量库构建与查询
│   │   ├── knowledge_service.py      # 知识库管理：表/规则/FewShot CRUD、Neo4j 同步
│   │   ├── neo4j_graph.py            # Neo4j 图操作：关系边 CRUD、Harness 知识索引
│   │   ├── neo4j_vector_store.py     # Neo4j 向量存储：表结构/FewShot/规则/进化示例索引
│   │   ├── db_pool.py                # 数据库连接池管理（双库）
│   │   ├── chat_repository.py        # 聊天历史存储
│   │   ├── user_repository.py        # 用户认证持久化层
│   │   └── graph_repository.py       # PG 图边数据库操作
│   ├── harness/                      # Harness 数据飞轮
│   │   ├── repository.py             # 数据库 CRUD（5 张 nl2sql_* 表）
│   │   ├── runner.py                 # 回归测试执行器
│   │   ├── evolution.py              # 规则进化（从失败中学习）
│   │   ├── knowledge.py              # 运行时知识加载（规则 + 进化 FewShot）
│   │   ├── online_service.py         # 在线 Harness 服务编排
│   │   └── llm_labeler.py            # LLM 自动标注失败案例
│   └── utils/
│       ├── sql_validator.py          # SQL 安全校验（关键字黑名单 + LIMIT）
│       └── lifespan.py               # 应用生命周期管理（初始化/清理）
│
├── data/                             # 数据文件
│   ├── mes_knowledge_base.txt        # MES 表结构知识库（DDL，按 --- 分块）
│   ├── dify_few_shot.txt             # SQL 示例库（问题-SQL 对）
│   ├── dify_sql_prompt.txt           # SQL 生成 Prompt 模板
│   ├── mes_relation_graph.json       # 表关系图（用于 Neo4j 初始化和 BFS 扩展）
│   ├── query_execution_report.txt    # 查询执行报告
│   ├── harness/
│   │   ├── cases.json                # 本地测试用例
│   │   ├── runtime_rules.json        # 本地运行时规则
│   │   └── evolved_few_shot.txt      # 本地进化 FewShot
│   └── backup/                       # 知识库文件的定时备份
│
├── scripts/                          # 运维脚本
│   ├── sync_kb_to_neo4j.py           # 同步知识库到 Neo4j
│   ├── generate_graph.py             # 生成关系图 JSON
│   ├── gen_graph_json.py             # 生成关系图 JSON（另一版本）
│   ├── rebuild_knowledge_base.py     # 重建知识库
│   ├── import_graph_to_neo4j.py      # 导入关系图到 Neo4j
│   ├── import_vectors_to_neo4j.py    # 导入向量到 Neo4j
│   ├── vectorize_evolved_few_shot.py # 向量化进化 FewShot
│   ├── vectorize_runtime_rules.py    # 向量化运行时规则
│   ├── check_all_embedding.py        # 检查 embedding 完整性
│   ├── check_all_fewshot.py          # 检查 FewShot 数据
│   ├── execute_business_queries.py   # 执行业务查询
│   └── ...                           # 更多运维脚本
│
├── web/                              # React 前端（Vite + TypeScript + Tailwind）
│   ├── src/
│   │   ├── App.tsx                   # 路由配置
│   │   ├── main.tsx                  # 应用入口
│   │   ├── types.ts                  # TypeScript 类型定义
│   │   ├── index.css                 # 全局样式 + Tailwind
│   │   ├── pages/                    # 页面组件（10 个页面）
│   │   │   ├── Home.tsx              # NL2SQL 查询主页
│   │   │   ├── LoginPage.tsx         # 登录页
│   │   │   ├── GraphPage.tsx         # 表关系图可视化
│   │   │   ├── TracePage.tsx         # Trace 追踪
│   │   │   ├── KnowledgePage.tsx     # 知识库管理
│   │   │   ├── KnowledgeSearchPage.tsx# 知识库检索
│   │   │   ├── FewShotManagement.tsx # FewShot 管理
│   │   │   ├── RuleManagement.tsx    # 运行时规则管理
│   │   │   ├── Harness.tsx           # Harness 管理
│   │   │   └── UserManagement.tsx    # 用户管理
│   │   ├── components/               # 通用组件
│   │   │   ├── AppLayout.tsx         # 侧边栏布局 + 导航
│   │   │   ├── CodeBlock.tsx         # SQL 代码块渲染
│   │   │   ├── MetricCard.tsx        # 指标卡片
│   │   │   ├── PaginationBar.tsx     # 分页组件
│   │   │   ├── Panel.tsx             # 通用面板
│   │   │   ├── SearchableSelect.tsx  # 可搜索下拉选择
│   │   │   ├── StatusBadge.tsx       # 状态徽章
│   │   │   ├── TracePanel.tsx        # Trace 面板
│   │   │   └── Empty.tsx             # 空状态占位
│   │   ├── hooks/                    # 自定义 Hooks
│   │   │   ├── useAuth.ts            # 认证状态
│   │   │   ├── useTheme.ts           # 主题切换
│   │   │   └── useUser.ts            # 用户信息
│   │   └── lib/
│   │       ├── api.ts                # API 调用封装
│   │       └── utils.ts              # 工具函数
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
│
├── docs/                             # 文档
│   └── knowledge_base_guide.md       # 知识库维护指南
│
├── files/                            # 参考文件（非运行时依赖）
│   ├── dify_code_node_v2.py
│   ├── dify_prompt_v2.txt
│   └── workflow_v2.md
│
├── public.sql                        # MES 业务表 DDL 样例
├── mes联表测试问题清单_含完整SQL.csv   # 联表回归测试用例
├── mes数据库.txt                      # 数据库表结构参考
└── mes数据库关联关系.json              # 表关联关系参考
```

---

## 7. 环境配置

### 7.1 环境要求

- Python >= 3.11
- PostgreSQL（需启用 pgvector 扩展）
- Neo4j（图数据库 + 向量索引）
- DeepSeek（或 OpenAI 兼容）API Key

### 7.2 关键配置项

```bash
# ── LLM ──────────────────────────────────
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash
INTENT_MODEL=Qwen/Qwen2.5-7B-Instruct

# ── Embedding ────────────────────────────
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5

# ── Neo4j ────────────────────────────────
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
USE_NEO4J_FOR_GRAPH=true

# ── Database ─────────────────────────────
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/mes
PROJECT_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/postgres
SQL_EXECUTION_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/mes

# ── Harness ──────────────────────────────
ENABLE_ONLINE_HARNESS=true
HARNESS_AUTO_INIT_DB=true
HARNESS_REQUEST_LOG_ENABLED=true
HARNESS_RUNTIME_CACHE_TTL_SECONDS=60

# ── BFS ──────────────────────────────────
BFS_MAX_HOPS=2
BFS_MAX_TABLES=10

# ── Retrieval ────────────────────────────
RETRIEVAL_TOP_K=8
FEW_SHOT_TOP_K=3
RETRIEVAL_SIMILARITY_THRESHOLD=0.55
DEFAULT_LIMIT=500
```

---

## 8. 安装与启动

### 8.1 安装依赖

```bash
uv sync --dev
```

### 8.2 初始化数据库

在项目内部库中启用 pgvector：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 8.3 初始化 Neo4j

导入关系图和向量数据：

```bash
uv run python scripts/import_graph_to_neo4j.py
uv run python scripts/import_vectors_to_neo4j.py
```

或通过 API 在线同步：

```bash
curl -X POST http://localhost:8000/api/graph/sync
```

### 8.4 启动服务

```bash
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

开发模式（热重载）：

```bash
uv run uvicorn src.main:app --reload
```

### 8.5 前端开发

```bash
cd web
npm install
npm run dev         # 开发模式
npm run build       # 生产构建，输出到 web/dist/
```

---

## 9. Harness 数据飞轮

### 9.1 设计理念

```
用户查询 → NL2SQL → 执行结果
                ↓ (失败时 / 点踩时)
          失败案例入库 (nl2sql_failure_case)
                ↓
         LLM 自动标注 + 多维度评估
                ↓
         分析生成候选规则 (nl2sql_rule_candidate)
                ↓
         人工审核 (approve / reject) + 去重检查
                ↓
         发布运行时规则 (nl2sql_runtime_knowledge)
                ↓
         注入 Prompt → 下次查询命中更准
```

### 9.2 数据库表（项目内部库）

| 表名 | 用途 |
|------|------|
| `nl2sql_request_log` | 每次 NL2SQL 请求的完整日志 |
| `nl2sql_failure_case` | 执行失败的案例（待标注） |
| `nl2sql_failure_label` | 人工标注的正确 SQL |
| `nl2sql_rule_candidate` | 从失败中提取的候选规则（待审核） |
| `nl2sql_runtime_knowledge` | 已发布的运行时知识（版本化） |

### 9.3 LLM 自动标注

对失败案例进行多维度评估：
- SQL 语法正确性
- 业务语义匹配度
- 字段选择准确性
- JOIN 关系正确性
- 过滤条件完整性

### 9.4 线上进化

从 `nl2sql_request_log` 中筛选点踩或失败的请求，自动分析生成候选规则和进化 FewShot。

---

## 10. 代码质量

```bash
uv run ruff check --fix .    # Lint + 自动修复
uv run ruff format .         # 格式化
uv run mypy src/             # 类型检查
uv run pytest                # 运行测试
```

---

## 11. 常见问题

### 启动报 pgvector 错误

项目内部库未启用 vector 扩展：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### Neo4j 连接失败

检查 `NEO4J_URI` 配置是否正确，Neo4j 服务是否运行。

### SQL 一直查错库

检查：
- `PROJECT_DATABASE_URL` 是否指向项目内部库
- `SQL_EXECUTION_DATABASE_URL` 是否指向 MES 业务库

### 修改知识库后结果没变化

需重建向量索引：

```bash
uv run python scripts/import_vectors_to_neo4j.py
```

或通过 API 触发同步后重建。

### Harness 表不存在

确保 `ENABLE_ONLINE_HARNESS=true` 和 `HARNESS_AUTO_INIT_DB=true`，服务启动时会自动建表。
