# 对话式问答页面（流式输出 + 记忆功能）实施方案

## 一、需求概述

在现有 NL2SQL 调试控制台基础上，新增一个**独立的对话式问答页面**，支持：

1. **流式输出**：调用 NL2SQL 时，实时展示每个推理节点的进度（意图理解 → 检索 → BFS → Schema → SQL生成 → 安全校验 → 执行）
2. **对话记忆**：多轮对话中保持上下文，后续问题可引用前文的表/字段/查询结果
3. 与现有 `/console` 调试页面并存，互不影响

***

## 二、现状分析

### 2.1 前端现状

| 项目   | 详情                                          |
| ---- | ------------------------------------------- |
| 框架   | React 18 + TypeScript + Vite + Tailwind CSS |
| 路由   | **无路由**，单页应用，仅 `Home.tsx` 一个页面              |
| API  | 基于 `fetch` + JSON，无流式/SSE                   |
| 冗余依赖 | `react-router-dom` 和 `zustand` 已安装但未使用      |

### 2.2 后端现状

| 项目        | 详情                                                                          |
| --------- | --------------------------------------------------------------------------- |
| `/nl2sql` | POST 一次性返回，等全部7节点完成后组装 JSON                                                 |
| 流式        | **无**，但 `CompiledGraph` 天然支持 `.astream()`                                   |
| 记忆        | **无**，`state.py` 中有未使用的 `messages` 字段，`workflow.compile()` 无 `checkpointer` |
| 会话表       | **无**，Harness DB 有请求日志表但无 session\_id                                       |

### 2.3 关键可行性判断

* LangGraph 的 `CompiledGraph.astream(stream_mode="updates")` 直接可用，**无需修改任何节点代码**

* 前端 `react-router-dom` 已安装，可直接启用路由

* 后端 FastAPI 原生支持 `StreamingResponse` + SSE

***

## 三、总体架构

```
┌─────────────────────────────────────────────────────┐
│                    浏览器                              │
│  /console          /chat                             │
│  (现有调试页)       (新增对话页)                        │
│       │                 │                             │
│       │            EventSource (SSE)                   │
│       │                 │                             │
└───────┼─────────────────┼─────────────────────────────┘
        │                 │
        ▼                 ▼
┌──────────────────────────────────────────────────────┐
│              FastAPI (main.py)                        │
│  POST /nl2sql         POST /chat/stream               │
│  (不变)               (新增 SSE 流式)                    │
│       │                    │                          │
│  ainvoke              astream + checkpointer          │
│       │                    │                          │
└───────┼────────────────────┼──────────────────────────┘
        │                    │
        ▼                    ▼
┌──────────────────────────────────────────────────────┐
│            LangGraph CompiledGraph                    │
│                                                      │
│  intent → retrieval → bfs → schema → sql_gen         │
│    → safety → execute                                │
│                                                      │
│  + MemorySaver (内存记忆，多轮对话用 thread_id)         │
└──────────────────────────────────────────────────────┘
```

***

## 四、实施步骤

### Step 1：后端 — 新增 SSE 流式端点 + 对话记忆

#### 1.1 新增 `POST /chat/stream` 端点

**文件**: `src/main.py`

在现有 `nl2sql()` 函数之后新增一个异步生成器端点：

```python
from fastapi.responses import StreamingResponse
import json

@app.post("/chat/stream")
async def chat_stream(request: NL2SQLRequest):
    """对话式 NL2SQL，SSE 流式返回每个节点的执行状态。"""
    if _app is None:
        # 用 SSE 格式返回错误
        ...

    async def event_generator():
        config = {"configurable": {"thread_id": request.thread_id or str(uuid.uuid4())}}
        initial_state = {"query": request.query}
        async for chunk in _app.astream(initial_state, config, stream_mode="updates"):
            node_name = list(chunk.keys())[0]
            node_data = chunk[node_name]
            # 过滤掉过长的 schema 数据，只发送摘要
            event = {
                "node": node_name,
                "status": "progress",
                "data": _summarize_node_output(node_name, node_data),
            }
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        # 最终结果
        yield f"data: {json.dumps({'node': 'done', 'status': 'complete', 'data': ...})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**设计决策**：

* 使用 SSE（Server-Sent Events），比 WebSocket 更轻量，浏览器原生 `EventSource` 支持

* 每个节点执行完推送一条事件，前端可展示"意图理解中..."→"检索表结构中..."→"生成 SQL 中..."等进度

* 节点内部的大文本（schema\_docs、few\_shot\_docs）做摘要处理，只传长度和关键词，减少 SSE 流量

#### 1.2 前端请求模型扩展

**文件**: `src/models/schemas.py`

在 `NL2SQLRequest` 中新增可选字段：

```python
class ChatRequest(NL2SQLRequest):
    thread_id: str = Field("", description="对话线程ID，为空则新建对话")
```

新增 `NL2SQLRequest` 的可选 `thread_id` 字段，兼容现有接口：

```python
class NL2SQLRequest(BaseModel):
    query: str = Field(..., min_length=1)
    thread_id: str = Field("", description="可选：对话线程ID，用于多轮记忆")
```

#### 1.3 LangGraph 编译时添加 MemorySaver

**文件**: `src/graph/workflow.py`

```python
from langgraph.checkpoint.memory import MemorySaver

def build_workflow(schema_store, few_shot_store):
    # ... 现有节点组装逻辑不变 ...
    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)
```

**设计决策**：

* 使用 `MemorySaver`（内存），简单且无需额外数据库。重启服务后记忆会丢失，但对调试/测试场景已足够

* 如果后续需要持久化记忆，可无缝切换为 `PostgresSaver`（项目已有 PostgreSQL 连接）

#### 1.4 在意图理解节点中利用对话历史

**文件**: `src/graph/nodes.py`

在 `intent_node` 中，从 `state.get("messages")` 读取历史对话，注入到 LLM prompt 中：

```python
def intent_node(state: GraphState) -> dict:
    messages = state.get("messages", [])
    # 提取最近 3 轮对话作为上下文
    history_text = _format_recent_history(messages, max_turns=3)
    if history_text:
        query_with_context = f"对话历史：\n{history_text}\n\n当前问题：{state['query']}"
    else:
        query_with_context = state["query"]
    # ... 后续逻辑不变，但用 query_with_context 代替原 query ...
```

同时在 `sql_gen_node` 中也注入历史上下文，让 LLM 能引用前文提到的表名和字段。

***

### Step 2：前端 — 新增对话页面

#### 2.1 启用 React Router，双页面架构

**文件**: `src/App.tsx`

```tsx
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Home from "./pages/Home";
import Chat from "./pages/Chat";

export default function App() {
  return (
    <BrowserRouter basename="/console">
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/chat" element={<Chat />} />
      </Routes>
    </BrowserRouter>
  );
}
```

* 现有 Home 页面路径不变：`/console` → Home

* 新 Chat 页面路径：`/console/chat` → Chat

* 在 Home 页面顶部添加一个导航链接到 `/console/chat`

#### 2.2 新增 Chat 页面组件

**新建文件**: `src/pages/Chat.tsx`

页面布局：

```
┌──────────────────────────────────────────────┐
│  Header: "MES 对话助手"  [新对话]  [返回调试]   │
├──────────────────────┬───────────────────────┤
│                      │                       │
│   消息列表             │   当前上下文面板        │
│   (聊天气泡)          │   - 当前表: t_pd_wo     │
│                      │   - 当前 JOIN: ...     │
│   - 用户消息(右对齐)    │   - 生成的 SQL         │
│   - AI 进度卡片       │   - 历史对话摘要        │
│   - AI SQL 代码块     │                       │
│   - 流式打字效果       │                       │
│                      │                       │
├──────────────────────┴───────────────────────┤
│  [输入框]                              [发送] │
│  💡 试试：「上一条SQL查出的工单有哪些产线？」     │
└──────────────────────────────────────────────┘
```

**核心功能**：

| 功能         | 实现方式                                                            |
| ---------- | --------------------------------------------------------------- |
| 消息列表       | `useState<Message[]>` 维护，每条消息有 role/user/content/type/timestamp |
| 流式接收       | `EventSource` 连接 `/chat/stream`，逐条 `onmessage` 追加到当前 AI 消息      |
| 进度展示       | 收到 `intent`/`retrieval`/`bfs` 等节点事件时，在消息气泡内展示进度条/步骤指示器          |
| SQL 展示     | 收到 `sql_gen` 节点时，实时渲染 SQL 代码块（CodeBlock 组件复用）                   |
| 打字效果       | SSE 事件到达时追加文本，模拟流式打字                                            |
| thread\_id | 页面级 `useState` 维护，首次请求不带则后端创建并返回，后续请求携带                         |
| 新对话        | 清空消息列表 + 重置 thread\_id                                          |
| 上下文面板      | 右侧展示当前节点的关键信息（扩展表、JOIN提示、生成的SQL预览）                              |

#### 2.3 重用现有组件

| 组件            | 用途                 |
| ------------- | ------------------ |
| `CodeBlock`   | 展示生成的 SQL          |
| `StatusBadge` | 展示各节点状态（进行中/成功/失败） |
| `Panel`       | 右侧上下文面板容器          |
| `cn()`        | Tailwind class 合并  |

#### 2.4 API 层扩展

**文件**: `src/lib/api.ts`

新增函数：

```typescript
// 非流式对话（作为降级方案）
export async function chatNl2Sql(query: string, threadId?: string): Promise<Nl2SqlResponse> {
  return requestJson<Nl2SqlResponse>("/nl2sql", {
    method: "POST",
    body: JSON.stringify({ query, thread_id: threadId || "" }),
  });
}

// 流式对话（主要使用）
export function createChatStream(
  query: string,
  threadId: string,
  onEvent: (event: ChatStreamEvent) => void,
  onError: (error: Error) => void,
  onComplete: () => void
): EventSource {
  const params = new URLSearchParams({ query, thread_id: threadId });
  const eventSource = new EventSource(`/chat/stream?${params}`);
  // NOTE: EventSource 不支持 POST，需改为用 GET 或使用 fetch + ReadableStream
  // 实际实现用 fetch + ReadableStream 模拟 SSE，或以 GET 传参
  ...
}
```

**重要技术决策**：浏览器原生 `EventSource` 不支持 POST 和自定义 headers。需采用以下方案之一：

* **方案 A（推荐）**：`POST /chat/stream` 用 `fetch` + `ReadableStream` 手动解析 SSE 流（前端代码 \~30行）

* **方案 B**：改为 `GET /chat/stream?query=...&thread_id=...`（简单但 URL 有限长）

推荐方案 A，编写一个 `fetchSSE()` 工具函数。

#### 2.5 类型扩展

**文件**: `src/types.ts`

新增类型：

```typescript
export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  type: "text" | "sql" | "progress" | "error";
  timestamp: number;
  nodeStatus?: Record<string, "pending" | "running" | "done" | "error">;
}

export interface ChatStreamEvent {
  node: string;
  status: "progress" | "complete" | "error";
  data: Record<string, unknown>;
  final_sql?: string;
  error?: string;
}
```

***

### Step 3：后端 — 对话历史持久化（可选增强）

如果 `MemorySaver` 不满足需求（重启丢失），可在 Harness DB 中新增会话表：

**文件**: `src/harness/repository.py`

新增两张表：

* `nl2sql_conversation`：会话记录（id, thread\_id, title, created\_at, updated\_at）

* `nl2sql_message`：消息记录（id, conversation\_id, role, content, created\_at）

此步骤为**可选增强**，第一版先用 MemorySaver 即可。

***

## 五、文件变更清单

| 文件                       | 操作     | 说明                                             |
| ------------------------ | ------ | ---------------------------------------------- |
| `src/main.py`            | 修改     | 新增 `POST /chat/stream` 端点                      |
| `src/models/schemas.py`  | 修改     | NL2SQLRequest 增加 `thread_id` 可选字段              |
| `src/graph/workflow.py`  | 修改     | `build_workflow` 添加 `MemorySaver` checkpointer |
| `src/graph/nodes.py`     | 修改     | intent\_node/sql\_gen\_node 注入对话历史上下文          |
| `src/graph/state.py`     | 修改     | 确认 messages 字段的 reducer 正确配置                   |
| `web/src/App.tsx`        | 修改     | 添加 BrowserRouter + Routes                      |
| `web/src/pages/Home.tsx` | 修改     | 顶部增加导航到 Chat 页面的链接                             |
| `web/src/pages/Chat.tsx` | **新建** | 对话页面主组件                                        |
| `web/src/lib/api.ts`     | 修改     | 新增流式 API 调用函数                                  |
| `web/src/types.ts`       | 修改     | 新增 Message、ChatStreamEvent 类型                  |
| `web/src/lib/stream.ts`  | **新建** | fetchSSE 工具函数（手动解析 SSE 流）                      |
| `web/vite.config.ts`     | 修改     | 确认 `/chat/stream` 代理配置                         |

***

## 六、验证计划

1. **启动服务**：`uv run uvicorn src.main:app --host 0.0.0.0 --port 8000`
2. **访问新页面**：`http://127.0.0.1:8000/console/chat`
3. **单轮测试**：输入「查询所有工单」，确认流式展示各节点进度，最终输出 SQL
4. **多轮测试**：继续输入「再查这些工单对应的料号信息」，确认 LLM 能理解"这些"指的是前文工单
5. **新对话测试**：点击"新对话"按钮，确认 thread\_id 重置，记忆清空
6. **与旧页面共存**：访问 `/console` 确认原有调试功能不受影响

***

## 七、假设与决策

| 决策点    | 选择                     | 理由                                 |
| ------ | ---------------------- | ---------------------------------- |
| 流式协议   | SSE                    | 比 WebSocket 轻量，单向推送足够，FastAPI 原生支持 |
| 前端流式实现 | fetch + ReadableStream | EventSource 不支持 POST，需要手动解析        |
| 记忆实现   | MemorySaver（内存）        | 第一版够用，无需数据库改造；后续可升级为 PostgresSaver |
| 历史持久化  | 第一版不做                  | MemorySaver 重启丢失可接受，第二版再补数据库持久化    |
| 路由方案   | react-router-dom       | 已安装，直接复用，不引入新依赖                    |
| 节点数据摘要 | 只传长度+状态                | 避免 SSE 流中传输大量 schema 文本            |

