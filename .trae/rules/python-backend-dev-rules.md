# Python 后端开发规范

## 1. 项目初始化与 uv 管理

### 1.1 创建项目

```bash
# 初始化项目（交互式）
uv init

# 或指定项目目录
uv init my-project
```

### 1.2 依赖管理

```bash
# 添加运行时依赖
uv add fastapi uvicorn pydantic sqlalchemy

# 添加开发依赖
uv add --dev pytest ruff mypy pre-commit

# 同步环境（按照 pyproject.toml + uv.lock 安装所有依赖）
uv sync

# 同步环境并包含开发依赖
uv sync --dev

# 移除依赖
uv remove some-package

# 锁定依赖版本
uv lock

# 更新所有依赖到最新兼容版本
uv lock --upgrade
```

### 1.3 运行命令

```bash
# 在项目虚拟环境中运行脚本/命令
uv run python main.py
uv run pytest
uv run ruff check .
uv run mypy src/

# 激活虚拟环境（Windows PowerShell）
.venv\Scripts\activate
```

### 1.4 pyproject.toml 模板

```toml
[project]
name = "my-project"
version = "0.1.0"
description = "项目描述"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.11.0",
    "mypy>=1.0",
    "pre-commit>=4.0",
]

[tool.ruff]
line-length = 120
target-version = "py311"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "B",   # flake8-bugbear
    "C4",  # flake8-comprehensions
    "UP",  # pyupgrade
    "SIM", # flake8-simplify
]
ignore = ["E501"]  # 行长度由 formatter 处理

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
skip-magic-trailing-comma = false

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true
```

---

## 2. 项目目录结构

```
project-root/
├── .venv/              # 虚拟环境（uv 自动创建，不入 git）
├── .trae/              # Trae IDE 配置与规则
├── src/                # 源代码根目录
│   ├── __init__.py
│   ├── main.py         # 应用入口
│   ├── api/            # API 路由层
│   │   ├── __init__.py
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   └── users.py
│   │   └── deps.py     # 依赖注入
│   ├── core/           # 核心配置
│   │   ├── __init__.py
│   │   ├── config.py   # 配置管理
│   │   └── security.py # 安全相关
│   ├── models/         # 数据模型（ORM / Pydantic）
│   │   ├── __init__.py
│   │   ├── db.py       # SQLAlchemy 模型
│   │   └── schemas.py  # Pydantic 请求/响应模型
│   ├── services/       # 业务逻辑层
│   │   ├── __init__.py
│   │   └── user_service.py
│   └── utils/          # 工具函数
│       ├── __init__.py
│       └── helpers.py
├── tests/              # 测试目录
│   ├── __init__.py
│   ├── conftest.py     # pytest 共享 fixtures
│   ├── test_api/
│   └── test_services/
├── scripts/            # 运维/迁移脚本
├── pyproject.toml      # 项目元数据与工具配置
├── uv.lock             # 锁定文件（提交到 git）
└── .gitignore
```

### 2.1 .gitignore 必备项

```gitignore
.venv/
__pycache__/
*.pyc
.env
.env.*
dist/
build/
*.egg-info/
.ruff_cache/
.mypy_cache/
.pytest_cache/
```

---

## 3. 代码风格

### 3.1 格式化：使用 Ruff

```bash
# 代码检查
uv run ruff check .

# 自动修复
uv run ruff check --fix .

# 代码格式化
uv run ruff format .

# 两者一起执行（推荐）
uv run ruff check --fix . && uv run ruff format .
```

**配置要点：**
- 行宽：120 字符
- 引号风格：双引号
- import 排序：自动处理（isort 规则已内置）

### 3.2 命名约定

| 类型 | 命名风格 | 示例 |
|------|---------|------|
| 模块/文件 | snake_case | `user_service.py` |
| 类 | PascalCase | `UserService` |
| 函数/方法 | snake_case | `get_user_by_id()` |
| 变量 | snake_case | `user_list` |
| 常量 | UPPER_SNAKE | `MAX_RETRY_COUNT` |
| 私有成员 | 前缀 `_` | `_internal_method()` |

### 3.3 Import 规范

```python
# 1. 标准库
import os
from typing import Optional

# 2. 第三方库
from fastapi import FastAPI, Depends
from pydantic import BaseModel

# 3. 本地模块
from src.core.config import settings
from src.models.schemas import UserResponse
```

- 禁止使用 `from module import *`
- 禁止循环导入

### 3.4 类型注解

所有公共函数/方法必须有完整的类型注解：

```python
from typing import Optional

async def get_user(user_id: int) -> Optional[dict]:
    """通过 ID 获取用户"""
    ...

def create_user(name: str, email: str, age: int = 0) -> dict:
    """创建用户"""
    ...
```

### 3.5 Docstring

使用 Google 风格 docstring（仅对公共 API 和复杂逻辑）：

```python
def transfer_money(from_account: str, to_account: str, amount: float) -> bool:
    """执行账户转账。

    Args:
        from_account: 转出账户编号
        to_account: 转入账户编号
        amount: 转账金额（正数）

    Returns:
        转账成功返回 True，否则返回 False

    Raises:
        ValueError: 当余额不足时抛出
    """
    ...
```

---

## 4. FastAPI 开发规范

### 4.1 路由组织

```python
# src/api/v1/users.py
from fastapi import APIRouter

router = APIRouter(prefix="/users", tags=["用户管理"])

@router.get("/")
async def list_users():
    ...

@router.post("/")
async def create_user():
    ...

@router.get("/{user_id}")
async def get_user(user_id: int):
    ...
```

### 4.2 请求/响应模型

```python
from pydantic import BaseModel, Field
from datetime import datetime

class UserCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="用户名")
    email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$")

class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}
```

### 4.3 异常处理

```python
from fastapi import HTTPException, status

@router.get("/{user_id}")
async def get_user(user_id: int):
    user = await user_service.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"用户 {user_id} 不存在",
        )
    return user
```

### 4.4 依赖注入

```python
# src/api/deps.py
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session

# 使用
@router.get("/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    ...
```

---

## 5. 类型检查

```bash
# 运行 mypy 静态类型检查
uv run mypy src/
```

配置在 pyproject.toml 中：

```toml
[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
```

---

## 6. 测试规范

### 6.1 使用 pytest

```bash
# 运行全部测试
uv run pytest

# 运行特定文件
uv run pytest tests/test_api/test_users.py

# 详细输出
uv run pytest -v

# 覆盖率
uv run pytest --cov=src --cov-report=html
```

### 6.2 测试命名

- 测试文件：`test_<模块名>.py`
- 测试函数：`test_<被测试函数>_<场景>`

```python
# tests/test_services/test_user_service.py
async def test_get_user_by_id_found():
    ...

async def test_get_user_by_id_not_found():
    ...

async def test_create_user_with_valid_data():
    ...
```

### 6.3 conftest.py 共享 fixture

```python
# tests/conftest.py
import pytest

@pytest.fixture
def sample_user_data():
    return {"name": "test_user", "email": "test@example.com"}
```

---

## 7. Git 提交规范

### 7.1 分支命名

```
feature/<功能简述>   # 新功能
fix/<问题简述>       # Bug 修复
refactor/<内容>      # 重构
```

### 7.2 Commit Message

```
<type>: <简短描述>

<详细说明（可选）>
```

type 取值：
- `feat`: 新功能
- `fix`: Bug 修复
- `refactor`: 重构
- `docs`: 文档
- `test`: 测试
- `chore`: 构建/工具

示例：
```
feat: 添加用户登录接口

支持用户名密码登录，返回 JWT token
```

---

## 8. 环境变量管理

使用 `.env` 文件 + pydantic-settings：

```python
# src/core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "My App"
    database_url: str = "postgresql+asyncpg://localhost:5432/mydb"
    secret_key: str

    model_config = {"env_file": ".env"}

settings = Settings()
```

---

## 9. 常用命令速查

```bash
# 项目初始化
uv init                         # 新建项目
uv sync --dev                   # 安装依赖

# 添加/移除依赖
uv add <package>                # 添加运行时依赖
uv add --dev <package>          # 添加开发依赖
uv remove <package>             # 移除依赖

# 代码质量
uv run ruff check --fix .       # Lint + 自动修复
uv run ruff format .            # 格式化
uv run mypy src/                # 类型检查

# 测试
uv run pytest                   # 全部测试
uv run pytest -v                # 详细模式
uv run pytest --cov=src         # 带覆盖率

# 运行
uv run python src/main.py       # 启动应用
uv run uvicorn src.main:app --reload
```