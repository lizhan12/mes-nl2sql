# SQL 查询结果分页功能实现方案

## 概述

在前端 Console 页面（`/console`）为 SQL 查询结果增加分页功能，支持上一页/下一页翻页。后端新增分页查询接口，前端在每个 SQL 结果的表格下方添加分页控件（含页码信息与加载/禁用状态）。

---

## 当前状态分析

### 后端现状
- SQL 执行函数 `_execute_sql()` 在 `nodes.py` 第 767 行，执行 SQL 后 `fetchall()` 获取全部数据，但只返回前 5 行作为 `preview`
- 安全校验阶段自动补 `LIMIT 500`
- 后端 **无任何分页接口**，没有 `page`/`page_size`/`offset` 参数
- `_get_db_url()` 函数（`nodes.py`）返回去除 `+asyncpg` 后缀的数据库 URL

### 前端现状
- 结果显示在 `ChatBubble`（单 SQL）和 `MultiSqlTabs`（多 SQL Tab）组件中
- 数据表格使用 `columns` 作为表头，`preview` 数组作为行数据
- 初始结果通过 SSE 流 `done` 事件一次性返回，包含 `rows`（总数）和 `preview`（前 5 行）
- 多个对话通过 `messages` 数组管理，每个 message 有独立的 SQL 和结果

### 关键约束
- 同一页面可能有多轮对话，每条消息的 SQL 和结果独立，分页需正确关联
- 多 SQL 模式下每条 SQL 有独立结果和 Tab，分页也需各自独立

---

## 修改方案

### 一、后端改动

#### 1. 新增 Pydantic 模型 — `src/models/schemas.py`

新增 `SqlPageRequest` 和 `SqlPageResponse`：

```python
class SqlPageRequest(BaseModel):
    """分页查询请求。"""
    sql: str = Field(..., min_length=1, description="要执行的 SQL 语句")
    page: int = Field(1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(20, ge=5, le=200, description="每页行数")

class SqlPageResponse(BaseModel):
    """分页查询响应。"""
    success: bool
    total_rows: int
    page: int
    page_size: int
    total_pages: int
    columns: list[str]
    rows: list[dict]
    error: str = ""
```

#### 2. 新增分页执行函数 — `src/graph/nodes.py`

在 `_execute_sql` 函数后面添加 `execute_paginated_sql` 函数：

```python
def execute_paginated_sql(sql: str, page: int = 1, page_size: int = 20) -> dict:
    """分页执行 SQL，返回指定页的数据。

    Args:
        sql: 原始 SQL 语句
        page: 页码（从 1 开始）
        page_size: 每页行数

    Returns:
        {"success": bool, "total_rows": int, "page": int, "page_size": int,
         "total_pages": int, "columns": [...], "rows": [...], "error": str}
    """
    try:
        # 用子查询包裹原 SQL，实现分页
        offset = (page - 1) * page_size
        count_sql = f"SELECT COUNT(*) FROM ({sql}) AS _cnt"
        page_sql = f"SELECT * FROM ({sql}) AS _page LIMIT {page_size} OFFSET {offset}"

        with psycopg.connect(_get_db_url()) as conn, conn.cursor() as cur:
            # 1) 统计总行数
            cur.execute(count_sql)
            total_rows = cur.fetchone()[0]

            # 2) 查询分页数据
            cur.execute(page_sql)
            if cur.description:
                columns = [d.name for d in cur.description]
                rows_data = cur.fetchall()
                rows = [dict(zip(columns, row, strict=True)) for row in rows_data]
            else:
                columns = []
                rows = []

        total_pages = max(1, (total_rows + page_size - 1) // page_size)

        return {
            "success": True,
            "total_rows": total_rows,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "columns": columns,
            "rows": rows,
            "error": "",
        }
    except Exception as e:
        return {
            "success": False,
            "total_rows": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
            "columns": [],
            "rows": [],
            "error": str(e),
        }
```

#### 3. 新增分页路由 — `src/main.py`

新增 `POST /execute/page` 端点：

```python
@app.post("/execute/page", response_model=SqlPageResponse)
async def execute_page(req: SqlPageRequest):
    """分页执行 SQL。"""
    from src.graph.nodes import execute_paginated_sql
    result = execute_paginated_sql(req.sql, req.page, req.page_size)
    return SqlPageResponse(**result)
```

同时补充 imports。

---

### 二、前端改动

#### 1. 新增类型定义 — `web/src/types.ts`

```typescript
export interface PageRequest {
  sql: string;
  page: number;
  page_size: number;
}

export interface PageResponse {
  success: boolean;
  total_rows: number;
  page: number;
  page_size: number;
  total_pages: number;
  columns: string[];
  rows: Array<Record<string, JsonValue>>;
  error: string;
}
```

#### 2. 新增 API 函数 — `web/src/lib/api.ts`

```typescript
export function fetchPage(sql: string, page: number, pageSize = 20): Promise<PageResponse> {
  return requestJson<PageResponse>("/execute/page", {
    method: "POST",
    body: JSON.stringify({ sql, page, page_size: pageSize }),
  });
}
```

#### 3. 新增 PaginationBar 组件 — 新建 `web/src/components/PaginationBar.tsx`

提取通用分页控件：

```tsx
interface PaginationBarProps {
  page: number;           // 当前页码
  totalPages: number;     // 总页数
  totalRows: number;      // 总行数
  loading: boolean;       // 加载中
  onPageChange: (page: number) => void;
}

// 渲染：<< 上一页 | 第 X/Y 页，共 N 行 | 下一页 >>
// loading 时按钮 disabled + 显示加载指示器
```

#### 4. 修改 `ChatBubble` 组件 — `web/src/pages/Chat.tsx`

为单 SQL 模式添加分页：

- 新增 local state：
  - `currentPage: number`（默认 1）
  - `pagedData: PageResponse | null`（非第 1 页时存储 fetch 结果）
  - `pageLoading: boolean`
- 数据表格渲染逻辑：
  - 第 1 页：使用 `message.executionResult.preview`
  - 后续页：使用 `pagedData.rows`
- 在表格下方渲染 `<PaginationBar>`：
  - `totalRows` 来自初始结果的 `rows` 字段
  - 点击翻页时调用 `fetchPage(message.sql, targetPage)`
  - 同一消息的 SQL 始终不变（取自 `message.sql`），页码通过 state 管理

#### 5. 修改 `MultiSqlTabs` 组件 — `web/src/pages/Chat.tsx`

为多 SQL 每个 Tab 添加分页：

- 新增 local state 管理每个 tab 的分页：
  ```typescript
  const [pageStates, setPageStates] = useState<
    Record<number, { page: number; data: PageResponse | null; loading: boolean }>
  >({});
  ```
- 每个 tab 的表格渲染同上（第 1 页用 preview，后续页用 fetched data）
- 每个 tab 的表格下方渲染独立分页控件
- 切换 tab 时不影响其他 tab 的分页状态
- 每条 SQL 取自 `results[activeTab].sql`

---

## 假设与决策

1. **子查询包裹方案**：用 `SELECT * FROM (原SQL) AS _page LIMIT N OFFSET M` 包裹原 SQL 实现分页，简单可靠，兼容已有 LIMIT 子句（被包裹在子查询内）
2. **每页默认 20 行**，可配置范围 5-200
3. **第 1 页数据复用初始查询结果**，不额外请求后端，节省性能
4. **分页状态为组件 local state**，不存入 messages 数组，避免触及其他组件重渲染
5. **翻页时 SQL 从原始 message 中取**，确保与初始查询一致

---

## 涉及文件汇总

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/models/schemas.py` | 修改 | 新增 SqlPageRequest、SqlPageResponse |
| `src/graph/nodes.py` | 修改 | 新增 execute_paginated_sql 函数 |
| `src/main.py` | 修改 | 新增 POST /execute/page 路由 |
| `web/src/types.ts` | 修改 | 新增 PageRequest、PageResponse 类型 |
| `web/src/lib/api.ts` | 修改 | 新增 fetchPage 函数 |
| `web/src/components/PaginationBar.tsx` | 新建 | 通用分页控件组件 |
| `web/src/pages/Chat.tsx` | 修改 | ChatBubble + MultiSqlTabs 添加分页逻辑 |

## 验证步骤

1. 后端：启动服务后 `POST /execute/page` 传入已知 SQL，验证分页返回正确
2. 前端：`npm run build` 编译通过
3. 功能验证：
   - 单 SQL 查询结果表格下方显示分页控件
   - 点击"下一页"正确切换数据
   - 多轮对话各自的 SQL 结果分页互不干扰（换页后仅当前消息的表格更新）
   - 多 SQL Tab 切换后各 Tab 分页独立
   - 边界情况：只有 1 页时按钮正确禁用
