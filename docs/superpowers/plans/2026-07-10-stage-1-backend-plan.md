# 阶段 1：项目初始化与最小聊天后端实施计划

> **给后续 agentic workers 的说明：** 实施本计划时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项执行。所有步骤使用复选框跟踪。Docker 启停、依赖安装和真实模型调用由用户在本地执行。

**目标：** 从空仓库建立一个使用 uv 管理依赖、使用 Docker Compose 运行 PostgreSQL + pgvector、支持会话持久化和一次真实模型调用的 FastAPI 后端。

**架构：** FastAPI 和 Python 依赖运行在 Windows 宿主机的项目 `.venv` 中，PostgreSQL 18 + pgvector 0.8.5 单独运行在 Docker 中。HTTP 路由通过 ChatService、Repository 和 ModelClient 窄接口访问数据库及 LiteLLM，外部模型调用期间不保持数据库事务。

**技术栈：** Python 3.12.10、uv 0.11.28、FastAPI 0.139.0、Uvicorn 0.51.0、Pydantic 2.13.4、SQLAlchemy 2.0.51、psycopg 3.3.4、Alembic 1.18.5、LiteLLM 1.91.1、PostgreSQL 18、pgvector 0.8.5、pytest 9.1.1、ruff 0.15.21。

## 全局约束

1. 所有项目 Python 包只能安装到仓库根目录的 `.venv`，不得使用全局 `pip install`。
2. `.python-version` 必须固定为 `3.12.10`。
3. uv 必须固定使用 `0.11.28`；`.venv` 不提交，`uv.lock` 必须提交。
4. 直接依赖使用精确版本写入 `pyproject.toml`，传递依赖的精确版本由 `uv.lock` 记录。
5. `.env` 不提交；`.env.example` 必须包含所有配置键且不得包含真实 API 密钥。
6. Docker 镜像必须固定为 `pgvector/pgvector:0.8.5-pg18-bookworm`，不得使用 `latest`。
7. FastAPI 在宿主机运行；阶段 1 不为 FastAPI 创建 Docker 镜像。
8. 阶段 1 只实现默认模型调用，不实现模型白名单、fallback 和完整模型网关。
9. 阶段 1 不安装 LlamaIndex 和 Python `pgvector` 包。
10. 所有测试必须能够在没有真实 OpenAI 或 DeepSeek 密钥的情况下运行。
11. 所有说明文档和用户可见错误信息使用中文；代码标识符和 API 字段使用英文。

---

## 文件结构映射

```text
src/databricks_zh_expert/main.py                 FastAPI 应用工厂和应用实例
src/databricks_zh_expert/api/dependencies.py     FastAPI 依赖装配
src/databricks_zh_expert/api/health.py           健康检查路由
src/databricks_zh_expert/api/chat.py             会话和消息路由
src/databricks_zh_expert/core/config.py          .env 和环境变量配置
src/databricks_zh_expert/core/errors.py          领域错误和 HTTP 映射
src/databricks_zh_expert/core/logging.py         标准输出日志配置
src/databricks_zh_expert/db/base.py              SQLAlchemy DeclarativeBase
src/databricks_zh_expert/db/session.py           Engine、SessionFactory 和依赖
src/databricks_zh_expert/db/models.py            sessions/messages/model_calls 模型
src/databricks_zh_expert/chat/schemas.py          API 请求和响应模型
src/databricks_zh_expert/chat/repository.py       会话、消息和模型调用持久化
src/databricks_zh_expert/chat/service.py          最小聊天用例编排
src/databricks_zh_expert/llm/client.py            ModelClient 协议和结果类型
src/databricks_zh_expert/llm/litellm_client.py    LiteLLM 生产适配器
alembic/env.py                                    从 Settings 读取数据库 URL
alembic/versions/0001_initial.py                  初始数据库迁移
docker-compose.yml                                PostgreSQL + pgvector 服务
docker/postgres/init/01-create-test-db.sql        创建独立测试数据库
tests/conftest.py                                 测试数据库和依赖覆盖
tests/unit/                                       不访问 Docker 和模型网络的测试
tests/integration/                                使用测试 PostgreSQL 的测试
pyproject.toml                                    直接依赖、工具和测试配置
uv.lock                                           完整锁定依赖树，由 uv 生成
.env.example                                      本地配置模板
.python-version                                   Python 版本固定
README.md                                         完整 PowerShell 操作说明
```

---

### 任务 1：建立 uv 项目、固定 Python 和依赖版本

**文件：**

- 创建：`.python-version`
- 创建：`pyproject.toml`
- 创建：`src/databricks_zh_expert/__init__.py`
- 创建：`README.md`
- 修改：`.gitignore`
- 生成：`uv.lock`，由用户执行 uv 命令生成

**接口：**

- 产出：可以被 `uv sync --locked` 复现的项目 `.venv`。
- 产出：可导入的 `databricks_zh_expert` Python 包。
- 后续依赖：所有后续命令都通过 `uv run --locked` 执行。

- [ ] **步骤 1：确认宿主机已有环境**

用户在 PowerShell 执行：

```powershell
python --version
docker --version
docker compose version
```

预期：Python 输出 `Python 3.12.10`；Docker 和 Docker Compose 均输出版本号。任何一项失败都先修复本地环境，不进入下一步。

- [ ] **步骤 2：安装固定版本 uv**

用户可以先检查官方安装脚本：

```powershell
powershell -c "irm https://astral.sh/uv/0.11.28/install.ps1 | more"
```

确认后执行官方固定版本安装命令：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/0.11.28/install.ps1 | iex"
```

重新打开 PowerShell，然后执行：

```powershell
uv --version
```

预期：输出 `uv 0.11.28`。uv 是唯一需要新增到用户环境的宿主机工具。

- [ ] **步骤 3：写入 Python 版本文件**

`.python-version` 的完整内容：

```text
3.12.10
```

- [ ] **步骤 4：创建项目清单**

`pyproject.toml` 使用以下内容：

```toml
[project]
name = "databricks-zh-expert"
version = "0.1.0"
description = "Databricks 顾问型 Agent Demo"
readme = "README.md"
requires-python = "==3.12.10"
dependencies = [
    "alembic==1.18.5",
    "fastapi==0.139.0",
    "litellm==1.91.1",
    "psycopg[binary]==3.3.4",
    "pydantic==2.13.4",
    "pydantic-settings==2.14.2",
    "python-dotenv==1.2.2",
    "sqlalchemy[asyncio]==2.0.51",
    "uvicorn[standard]==0.51.0",
]

[dependency-groups]
dev = [
    "httpx==0.28.1",
    "pytest==9.1.1",
    "pytest-asyncio==1.4.0",
    "pytest-cov==7.1.0",
    "ruff==0.15.21",
]

[build-system]
requires = ["hatchling==1.31.0"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/databricks_zh_expert"]

[tool.pytest.ini_options]
addopts = "-ra --strict-markers --strict-config"
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.coverage.run]
branch = true
source = ["databricks_zh_expert"]

[tool.coverage.report]
fail_under = 80
show_missing = true

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
```

- [ ] **步骤 5：创建最小 Python 包和 README**

`src/databricks_zh_expert/__init__.py`：

```python
__version__ = "0.1.0"
```

`README.md` 初始内容：

```markdown
# Databricks 中文专家 Agent

本项目是一个 Databricks 顾问型 Agent Demo。阶段 1 提供 FastAPI、PostgreSQL 会话持久化和最小模型调用。
```

- [ ] **步骤 6：补充 Git 忽略规则**

确认 `.gitignore` 至少包含：

```gitignore
.env
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
```

不要忽略 `.env.example`、`.python-version` 或 `uv.lock`。

- [ ] **步骤 7：由用户生成锁文件和项目环境**

用户在仓库根目录执行：

```powershell
uv lock
uv sync --locked
uv tree --depth 1
uv run --locked python --version
```

预期：

1. 仓库根目录生成 `uv.lock` 和 `.venv`。
2. Python 输出 `Python 3.12.10`。
3. `uv tree --depth 1` 显示 `pyproject.toml` 中的运行依赖和开发依赖。
4. 全局 Python 环境没有被修改。

- [ ] **步骤 8：建议提交点**

```powershell
git add .gitignore .python-version pyproject.toml uv.lock README.md src/databricks_zh_expert/__init__.py
git commit -m "chore: initialize uv python project"
```

---

### 任务 2：建立 `.env` 配置模板和 PostgreSQL Compose

**文件：**

- 创建：`.env.example`
- 创建：`docker-compose.yml`
- 创建：`docker/postgres/init/01-create-test-db.sql`

**接口：**

- 产出：开发数据库 `databricks_agent`，连接地址来自 `DATABASE_URL`。
- 产出：测试数据库 `databricks_agent_test`，连接地址来自 `TEST_DATABASE_URL`。
- 产出：Compose 服务名固定为 `postgres`。

- [ ] **步骤 1：创建 `.env.example`**

```dotenv
APP_NAME=Databricks 中文专家 Agent
APP_ENV=development
APP_HOST=127.0.0.1
APP_PORT=8000
LOG_LEVEL=INFO

POSTGRES_DB=databricks_agent
POSTGRES_USER=databricks_agent
POSTGRES_PASSWORD=databricks_agent_dev
POSTGRES_PORT=5432
DATABASE_URL=postgresql+psycopg://databricks_agent:databricks_agent_dev@localhost:5432/databricks_agent
TEST_DATABASE_URL=postgresql+psycopg://databricks_agent:databricks_agent_dev@localhost:5432/databricks_agent_test

DEFAULT_MODEL=deepseek/deepseek-v4-flash
MODEL_REQUEST_TIMEOUT_SECONDS=60
OPENAI_API_KEY=
DEEPSEEK_API_KEY=
```

`DEFAULT_MODEL` 使用 LiteLLM 的 provider-qualified 名称；阶段 2 再增加面向业务的模型别名和白名单映射。

- [ ] **步骤 2：创建测试数据库初始化脚本**

`docker/postgres/init/01-create-test-db.sql`：

```sql
CREATE DATABASE databricks_agent_test;
```

该脚本只在 Docker 数据卷首次初始化时执行。测试数据库名因此固定，不从 `.env` 动态生成。

- [ ] **步骤 3：创建 Docker Compose 文件**

`docker-compose.yml`：

```yaml
services:
  postgres:
    image: pgvector/pgvector:0.8.5-pg18-bookworm
    container_name: databricks-agent-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "${POSTGRES_PORT}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./docker/postgres/init:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 10s

volumes:
  postgres_data:
```

- [ ] **步骤 4：由用户创建本地 `.env`**

用户执行：

```powershell
Copy-Item .env.example .env
```

然后编辑 `.env`。数据库开发密码可以保留本地示例值；真实调用 DeepSeek 时填写 `DEEPSEEK_API_KEY`。不得把 `.env` 加入 Git。

- [ ] **步骤 5：由用户检查并启动 Compose**

```powershell
docker compose config
docker compose up -d
docker compose ps
```

预期：`postgres` 状态最终显示为 `healthy`。

- [ ] **步骤 6：由用户验证 PostgreSQL 和 pgvector 可用性**

```powershell
docker compose exec postgres psql -U databricks_agent -d databricks_agent -c "SELECT version();"
docker compose exec postgres psql -U databricks_agent -d databricks_agent -c "SELECT default_version FROM pg_available_extensions WHERE name = 'vector';"
docker compose exec postgres psql -U databricks_agent -d databricks_agent_test -c "SELECT current_database();"
```

预期：

1. PostgreSQL 主版本为 18。
2. `vector` 的可用版本为 0.8.5。
3. 测试数据库返回 `databricks_agent_test`。

- [ ] **步骤 7：建议提交点**

```powershell
git add .env.example docker-compose.yml docker/postgres/init/01-create-test-db.sql
git commit -m "chore: add postgres pgvector compose service"
```

---

### 任务 3：实现配置加载、数据库会话和健康检查

**文件：**

- 创建：`src/databricks_zh_expert/core/config.py`
- 创建：`src/databricks_zh_expert/core/errors.py`
- 创建：`src/databricks_zh_expert/core/logging.py`
- 创建：`src/databricks_zh_expert/db/base.py`
- 创建：`src/databricks_zh_expert/db/session.py`
- 创建：`src/databricks_zh_expert/api/dependencies.py`
- 创建：`src/databricks_zh_expert/api/health.py`
- 创建：`src/databricks_zh_expert/main.py`
- 创建：`tests/unit/test_config.py`
- 创建：`tests/unit/test_health.py`

**接口：**

- 产出：`Settings` 和缓存函数 `get_settings() -> Settings`。
- 产出：`get_db() -> AsyncIterator[AsyncSession]`。
- 产出：`create_app() -> FastAPI` 和模块级 `app`。
- 产出：`GET /health`，数据库正常返回 200，数据库异常返回 503。

- [ ] **步骤 1：先写配置失败测试**

`tests/unit/test_config.py` 至少覆盖：

```python
from pydantic import SecretStr

from databricks_zh_expert.core.config import Settings


def test_settings_use_expected_defaults() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:pass@localhost:5432/app",
        test_database_url="postgresql+psycopg://user:pass@localhost:5432/app_test",
    )

    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 8000
    assert settings.default_model == "deepseek/deepseek-v4-flash"
    assert settings.model_request_timeout_seconds == 60
    assert settings.deepseek_api_key == SecretStr("")


def test_secret_is_masked_when_settings_are_rendered() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:pass@localhost:5432/app",
        test_database_url="postgresql+psycopg://user:pass@localhost:5432/app_test",
        deepseek_api_key="real-secret",
    )

    assert "real-secret" not in str(settings.model_dump())
```

- [ ] **步骤 2：运行测试并确认失败**

```powershell
uv run --locked pytest tests/unit/test_config.py -v
```

预期：因为 `databricks_zh_expert.core.config` 尚不存在而失败。

- [ ] **步骤 3：实现 Settings**

`core/config.py` 必须定义这些字段和配置：

```python
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Databricks 中文专家 Agent"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"
    database_url: str
    test_database_url: str
    default_model: str = "deepseek/deepseek-v4-flash"
    model_request_timeout_seconds: int = 60
    openai_api_key: SecretStr = SecretStr("")
    deepseek_api_key: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **步骤 4：实现数据库基础设施**

`db/base.py`：

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

`db/session.py` 必须提供：

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from databricks_zh_expert.core.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        yield session
```

- [ ] **步骤 5：先写健康检查失败测试**

`tests/unit/test_health.py` 使用 FastAPI dependency override 提供 Fake Session，至少验证：

```python
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from databricks_zh_expert.db.session import get_db
from databricks_zh_expert.main import create_app


class HealthySession:
    async def execute(self, statement: object) -> None:
        return None


async def healthy_db() -> AsyncIterator[HealthySession]:
    yield HealthySession()


def test_health_returns_ok_when_database_is_available() -> None:
    app = create_app()
    app.dependency_overrides[get_db] = healthy_db

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
```

再增加一个 Fake Session，使 `execute()` 抛出 `SQLAlchemyError`，断言 HTTP 503 和错误码 `database_unavailable`。

- [ ] **步骤 6：实现统一错误和健康路由**

`core/errors.py` 定义：

```python
from typing import Any


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)
```

`api/health.py` 使用 `Depends(get_db)`、`SELECT 1` 和 `SQLAlchemyError`。成功响应必须是：

```json
{"status":"ok","database":"ok"}
```

数据库异常必须抛出：

```python
AppError(
    code="database_unavailable",
    message="数据库暂时不可用。",
    status_code=503,
)
```

- [ ] **步骤 7：创建应用工厂和日志配置**

`core/logging.py` 使用标准库 `logging.basicConfig`，日志写标准输出，格式至少包含时间、级别、logger 和消息。

`main.py` 必须：

1. 定义 `create_app() -> FastAPI`。
2. 注册 `AppError` exception handler，响应结构为 `{"code", "message", "details"}`。
3. 注册 `RequestValidationError` handler，返回 HTTP 422、错误码 `validation_error` 和 Pydantic 错误明细。
4. 注册 health router。
5. 创建模块级 `app = create_app()`。
6. 不在日志中输出 Settings 完整内容。

`tests/unit/test_health.py` 再增加一个请求校验测试，确认无效 API 请求使用统一的 `validation_error` 响应结构，而不是 FastAPI 默认的 `detail` 顶层结构。

- [ ] **步骤 8：运行任务测试和静态检查**

```powershell
uv run --locked pytest tests/unit/test_config.py tests/unit/test_health.py -v
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

预期：全部通过。

- [ ] **步骤 9：建议提交点**

```powershell
git add src tests/unit
git commit -m "feat: add settings database session and health api"
```

---

### 任务 4：定义数据库模型和初始 Alembic 迁移

**文件：**

- 创建：`src/databricks_zh_expert/db/models.py`
- 创建：`alembic.ini`
- 创建：`alembic/env.py`
- 创建：`alembic/script.py.mako`
- 创建：`alembic/versions/0001_initial.py`
- 创建：`tests/conftest.py`
- 创建：`tests/integration/test_migrations.py`

**接口：**

- 产出：ORM 模型 `ChatSession`、`Message`、`ModelCall`。
- 产出：Alembic revision `0001_initial`。
- 数据库契约：启用 `vector` 扩展并创建 `sessions`、`messages`、`model_calls`。

- [ ] **步骤 1：先写迁移验证测试**

先在 `tests/conftest.py` 创建读取 `TEST_DATABASE_URL` 的 `test_engine` fixture。解析 URL 后必须断言数据库名以 `_test` 结尾，再创建异步 engine；fixture 结束时执行 `engine.dispose()`。

`tests/integration/test_migrations.py` 使用该 engine，并通过 `run_sync()` 调用 SQLAlchemy inspector。断言：

```python
EXPECTED_TABLES = {"alembic_version", "sessions", "messages", "model_calls"}


async def test_initial_migration_creates_expected_tables(test_engine) -> None:
    async with test_engine.connect() as connection:
        table_names = await connection.run_sync(
            lambda sync_connection: set(inspect(sync_connection).get_table_names())
        )

    assert EXPECTED_TABLES <= table_names
```

第二个断言执行：

```sql
SELECT extversion FROM pg_extension WHERE extname = 'vector'
```

并验证返回 `0.8.5`。

- [ ] **步骤 2：运行测试并确认失败**

确保 Docker 已由用户启动，然后执行：

```powershell
uv run --locked pytest tests/integration/test_migrations.py -v
```

预期：初始迁移和测试 fixture 尚不存在，因此失败。

- [ ] **步骤 3：定义 ORM 模型**

`db/models.py` 使用 UUID 主键和带时区时间戳。必须包含以下字段：

```python
class ChatSession(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID]
    title: Mapped[str]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID]
    session_id: Mapped[UUID]
    role: Mapped[str]
    content: Mapped[str]
    artifact_type: Mapped[str | None]
    created_at: Mapped[datetime]


class ModelCall(Base):
    __tablename__ = "model_calls"

    id: Mapped[UUID]
    session_id: Mapped[UUID]
    provider: Mapped[str]
    model: Mapped[str]
    prompt_tokens: Mapped[int | None]
    completion_tokens: Mapped[int | None]
    latency_ms: Mapped[int]
    success: Mapped[bool]
    error_message: Mapped[str | None]
    created_at: Mapped[datetime]
```

实现时使用：

1. `uuid4` 作为 Python 默认主键生成器。
2. `DateTime(timezone=True)` 和 `server_default=func.now()`。
3. `messages.session_id`、`model_calls.session_id` 外键指向 `sessions.id` 并设置 `ON DELETE CASCADE`。
4. `messages.role` 检查约束限制为 `system`、`user`、`assistant`。
5. `messages(session_id, created_at)` 和 `model_calls(session_id, created_at)` 复合索引。
6. `content` 使用 `Text`；`error_message` 使用 `Text`。

- [ ] **步骤 4：配置 Alembic**

`alembic.ini` 不写真实数据库 URL，保留占位的 `sqlalchemy.url`；`alembic/env.py` 必须从 `get_settings().database_url` 读取实际 URL，并导入 `Base.metadata` 和 `db.models`。

迁移环境使用 `async_engine_from_config`，支持 psycopg 异步驱动。不得从 `.env` 读取 `POSTGRES_*` 后自行拼接 URL。

- [ ] **步骤 5：编写初始迁移**

`alembic/versions/0001_initial.py` 固定：

```python
revision = "0001_initial"
down_revision = None
```

`upgrade()` 按以下顺序执行：

```python
op.execute("CREATE EXTENSION IF NOT EXISTS vector")
op.create_table(
    "sessions",
    sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("title", sa.String(length=200), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
    sa.PrimaryKeyConstraint("id"),
)
op.create_table(
    "messages",
    sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("role", sa.String(length=20), nullable=False),
    sa.Column("content", sa.Text(), nullable=False),
    sa.Column("artifact_type", sa.String(length=50), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
    sa.CheckConstraint(
        "role IN ('system', 'user', 'assistant')",
        name="ck_messages_role",
    ),
    sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id"),
)
op.create_table(
    "model_calls",
    sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("provider", sa.String(length=50), nullable=False),
    sa.Column("model", sa.String(length=100), nullable=False),
    sa.Column("prompt_tokens", sa.Integer(), nullable=True),
    sa.Column("completion_tokens", sa.Integer(), nullable=True),
    sa.Column("latency_ms", sa.Integer(), nullable=False),
    sa.Column("success", sa.Boolean(), nullable=False),
    sa.Column("error_message", sa.Text(), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    ),
    sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id"),
)
op.create_index(
    "ix_messages_session_created_at",
    "messages",
    ["session_id", "created_at"],
)
op.create_index(
    "ix_model_calls_session_created_at",
    "model_calls",
    ["session_id", "created_at"],
)
```

该文件必须导入 `sqlalchemy as sa` 和 `from sqlalchemy.dialects import postgresql`。`downgrade()` 依次删除两个索引、`model_calls`、`messages` 和 `sessions`。

`downgrade()` 只删除本阶段索引和三张业务表，不删除 `vector` 扩展，避免未来其他表使用扩展时被误删。

- [ ] **步骤 6：由用户迁移开发数据库**

```powershell
uv run --locked alembic upgrade head
uv run --locked alembic current
```

预期：current revision 为 `0001_initial`。

- [ ] **步骤 7：由用户迁移测试数据库**

PowerShell 临时覆盖 `DATABASE_URL`，完成后删除当前 shell 的覆盖值：

```powershell
$env:DATABASE_URL="postgresql+psycopg://databricks_agent:databricks_agent_dev@localhost:5432/databricks_agent_test"
uv run --locked alembic upgrade head
Remove-Item Env:DATABASE_URL
```

- [ ] **步骤 8：运行迁移测试**

```powershell
uv run --locked pytest tests/integration/test_migrations.py -v
```

预期：表结构和 vector 扩展测试通过。

- [ ] **步骤 9：建议提交点**

```powershell
git add alembic alembic.ini src/databricks_zh_expert/db/models.py tests/integration/test_migrations.py
git commit -m "feat: add initial postgres schema"
```

---

### 任务 5：实现会话 Repository 和会话 API

**文件：**

- 创建：`src/databricks_zh_expert/chat/schemas.py`
- 创建：`src/databricks_zh_expert/chat/repository.py`
- 更新：`src/databricks_zh_expert/api/dependencies.py`
- 创建：`src/databricks_zh_expert/api/chat.py`
- 更新：`src/databricks_zh_expert/main.py`
- 创建：`tests/integration/test_sessions_api.py`
- 更新：`tests/conftest.py`

**接口：**

- `ChatRepository.create_session(title: str) -> ChatSession`
- `ChatRepository.list_sessions(limit: int, offset: int) -> list[ChatSession]`
- `ChatRepository.get_session(session_id: UUID) -> ChatSession | None`
- `ChatRepository.list_messages(session_id: UUID, limit: int = 100) -> list[Message]`
- API：创建、列出和查看会话。

- [ ] **步骤 1：先写会话 API 失败测试**

先扩展 `tests/conftest.py`，增加测试 AsyncSession、覆盖 `get_db` 的 fixture，以及使用 `httpx.ASGITransport(app=app)` 的 AsyncClient fixture。每个测试结束时回滚事务或清理本测试写入的数据。

`tests/integration/test_sessions_api.py` 覆盖：

```python
async def test_create_and_get_session(client) -> None:
    create_response = await client.post(
        "/api/chat/sessions",
        json={"title": "每日销售分析"},
    )
    assert create_response.status_code == 201
    session_id = create_response.json()["id"]

    get_response = await client.get(f"/api/chat/sessions/{session_id}")
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "每日销售分析"
    assert get_response.json()["messages"] == []


async def test_get_missing_session_returns_domain_error(client) -> None:
    response = await client.get(
        "/api/chat/sessions/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404
    assert response.json()["code"] == "session_not_found"
```

再覆盖 `GET /api/chat/sessions?limit=20&offset=0`，验证按 `updated_at` 倒序。

- [ ] **步骤 2：运行测试并确认失败**

```powershell
uv run --locked pytest tests/integration/test_sessions_api.py -v
```

预期：chat schemas、repository 和路由尚不存在而失败。

- [ ] **步骤 3：定义会话和消息 Schema**

`chat/schemas.py` 必须定义：

```python
class SessionCreate(BaseModel):
    title: str = Field(default="新会话", min_length=1, max_length=200)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    role: str
    content: str
    artifact_type: str | None
    created_at: datetime


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class SessionDetail(SessionResponse):
    messages: list[MessageResponse]
```

- [ ] **步骤 4：实现 ChatRepository 的会话方法**

Repository 构造函数固定为：

```python
class ChatRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
```

要求：

1. `create_session()` 执行 `add`、`commit`、`refresh`。
2. `list_sessions()` 使用参数化 SQLAlchemy select，限制 `limit` 为 1 到 100。
3. `get_session()` 使用 UUID 精确查询。
4. `list_messages()` 按 `created_at` 正序返回。
5. Repository 不抛出 HTTPException。

- [ ] **步骤 5：实现会话路由和依赖装配**

`api/dependencies.py` 增加：

```python
def get_chat_repository(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ChatRepository:
    return ChatRepository(db)
```

`api/chat.py` 实现：

```text
POST /api/chat/sessions             201
GET  /api/chat/sessions             200
GET  /api/chat/sessions/{session_id} 200 或 404
```

会话不存在时抛出：

```python
AppError("session_not_found", "会话不存在。", 404)
```

`main.py` 注册 chat router，前缀固定为 `/api/chat`。

- [ ] **步骤 6：运行会话测试和静态检查**

```powershell
uv run --locked pytest tests/integration/test_sessions_api.py -v
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

预期：全部通过。

- [ ] **步骤 7：建议提交点**

```powershell
git add src/databricks_zh_expert/api src/databricks_zh_expert/chat src/databricks_zh_expert/main.py tests/integration/test_sessions_api.py
git commit -m "feat: add chat session api"
```

---

### 任务 6：实现最小 LiteLLM 调用和发送消息流程

**文件：**

- 创建：`src/databricks_zh_expert/llm/client.py`
- 创建：`src/databricks_zh_expert/llm/litellm_client.py`
- 创建：`src/databricks_zh_expert/chat/service.py`
- 更新：`src/databricks_zh_expert/chat/schemas.py`
- 更新：`src/databricks_zh_expert/chat/repository.py`
- 更新：`src/databricks_zh_expert/api/dependencies.py`
- 更新：`src/databricks_zh_expert/api/chat.py`
- 创建：`tests/unit/test_chat_service.py`
- 创建：`tests/integration/test_messages_api.py`
- 更新：`tests/conftest.py`

**接口：**

- `ModelClient.complete(messages: list[ModelMessage]) -> ModelResult`
- `ChatService.send_message(session_id: UUID, content: str) -> SendMessageResult`
- API：`POST /api/chat/sessions/{session_id}/messages`。

- [ ] **步骤 1：定义 ModelClient 契约**

`llm/client.py` 必须完整定义：

```python
from dataclasses import dataclass
from typing import Literal, Protocol

ModelRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: ModelRole
    content: str


@dataclass(frozen=True, slots=True)
class ModelResult:
    content: str
    provider: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None


class ModelClient(Protocol):
    @property
    def provider(self) -> str:
        raise NotImplementedError

    @property
    def model(self) -> str:
        raise NotImplementedError

    async def complete(self, messages: list[ModelMessage]) -> ModelResult:
        raise NotImplementedError
```

- [ ] **步骤 2：先写 ChatService 失败测试**

`tests/unit/test_chat_service.py` 创建 Fake Repository 和 Fake ModelClient，验证：

1. user message 在模型调用前保存。
2. 只向模型传递最近 20 条消息。
3. 成功时保存 assistant message 和成功 model_call。
4. 模型异常时保存失败 model_call，不保存 assistant message。
5. 模型异常转换为 `model_request_failed`，错误文本不得包含 API 密钥。

核心成功测试形状：

```python
class FakeModelClient:
    provider = "deepseek"
    model = "deepseek-v4-flash"

    async def complete(self, messages: list[ModelMessage]) -> ModelResult:
        return ModelResult(
            content="这是一个 Markdown 回答。",
            provider="deepseek",
            model="deepseek-v4-flash",
            prompt_tokens=12,
            completion_tokens=8,
        )


async def test_send_message_persists_reply_and_model_call() -> None:
    result = await service.send_message(session_id, "设计一个销售工作流")

    assert result.assistant_message.content == "这是一个 Markdown 回答。"
    assert repository.model_calls[0].success is True
    assert repository.model_calls[0].latency_ms >= 0
```

- [ ] **步骤 3：运行测试并确认失败**

```powershell
uv run --locked pytest tests/unit/test_chat_service.py -v
```

预期：ChatService 尚不存在而失败。

- [ ] **步骤 4：扩展 Repository 持久化接口**

增加精确接口 `create_message(self, session_id: UUID, role: str, content: str, artifact_type: str | None = None) -> Message`、`create_model_call(self, *, session_id: UUID, provider: str, model: str, prompt_tokens: int | None, completion_tokens: int | None, latency_ms: int, success: bool, error_message: str | None) -> ModelCall` 和 `list_recent_messages(self, session_id: UUID, limit: int = 20) -> list[Message]`。

每次写入独立 commit。保存 user message 后结束事务，再调用外部模型。`list_recent_messages()` 先按 `created_at DESC` 取最后 N 条，再反转为时间正序返回；`create_message()` 同时更新会话的 `updated_at`。

- [ ] **步骤 5：实现 ChatService**

构造函数固定为：

```python
class ChatService:
    def __init__(self, repository: ChatRepository, model_client: ModelClient) -> None:
        self.repository = repository
        self.model_client = model_client
```

`chat/service.py` 同时定义不可变的 `SendMessageResult`，字段为 `user_message: Message`、`assistant_message: Message` 和 `model_call: ModelCall`。

`send_message()` 顺序固定为：

1. 查询会话，不存在抛 `session_not_found`。
2. 保存 user message。
3. 加载最近 20 条消息并映射为 ModelMessage。
4. 使用 `time.perf_counter()` 测量模型耗时。
5. 调用 ModelClient。
6. 成功时保存 assistant message 和成功 model_call。
7. 异常时通过 `model_client.provider` 和 `model_client.model` 保存失败 model_call，只保存异常类型和截断到 500 字符的安全摘要。
8. 如果异常是 `model_not_configured`，记录失败后原样抛出，保持 HTTP 503。
9. 其他异常转换为 `AppError("model_request_failed", "模型调用失败，请稍后重试。", 502)`。

- [ ] **步骤 6：实现 LiteLLM 适配器**

`LiteLLMModelClient` 从 Settings 读取默认模型、超时和 SecretStr 密钥。调用：

```python
response = await litellm.acompletion(
    model=settings.default_model,
    messages=[{"role": item.role, "content": item.content} for item in messages],
    timeout=settings.model_request_timeout_seconds,
    api_key=api_key,
)
```

要求：

1. DeepSeek 模型且 `DEEPSEEK_API_KEY` 为空时，调用前抛出 `model_not_configured`，HTTP 503。
2. OpenAI 模型且 `OPENAI_API_KEY` 为空时采用相同行为。
3. 根据 provider 选择 SecretStr 并提取为局部变量 `api_key`，显式传给 LiteLLM，不写入日志或异常文本。
4. 返回文本为空时按模型调用失败处理。
5. 从 response usage 提取 token；usage 缺失时返回 `None`，不得猜测。
6. 不记录完整 messages 或 API key。

- [ ] **步骤 7：定义发送消息 Schema 和路由**

`chat/schemas.py` 增加：

```python
class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


class SendMessageResponse(BaseModel):
    session_id: UUID
    user_message: MessageResponse
    assistant_message: MessageResponse
    model_call_id: UUID
```

路由：

```text
POST /api/chat/sessions/{session_id}/messages
```

成功返回 201。`get_model_client()` 和 `get_chat_service()` 都在 `api/dependencies.py` 组装，使测试可以覆盖 ModelClient。

- [ ] **步骤 8：写消息 API 集成测试**

`tests/integration/test_messages_api.py` 使用依赖覆盖注入 Fake ModelClient，不调用公网。至少验证：

1. 创建会话后发送消息返回 201。
2. 返回 user 和 assistant 两条消息。
3. 再次查询会话能看到两条持久化消息。
4. 数据库存在一条成功 model_call。
5. 不存在会话返回 404。
6. 空消息返回 422。

- [ ] **步骤 9：运行模型和消息测试**

```powershell
uv run --locked pytest tests/unit/test_chat_service.py tests/integration/test_messages_api.py -v
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

预期：全部通过，且测试过程中没有任何真实模型网络请求。

- [ ] **步骤 10：由用户执行一次真实 DeepSeek 冒烟测试**

用户确认 `.env` 已填写 `DEEPSEEK_API_KEY`，启动服务：

```powershell
uv run --locked uvicorn databricks_zh_expert.main:app --reload --host 127.0.0.1 --port 8000
```

另开 PowerShell：

```powershell
$session = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/chat/sessions -ContentType "application/json" -Body '{"title":"阶段1冒烟测试"}'
$body = @{ content = "请用 Markdown 简要说明 Bronze、Silver、Gold 三层的区别。" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/chat/sessions/$($session.id)/messages" -ContentType "application/json" -Body $body
```

预期：返回 user message、assistant message 和 model_call_id。若供应商尚未开放配置的模型标识，应保留代码和配置结构，仅修改 `.env` 中实际可用的 provider-qualified 模型名；阶段 2 再固定白名单映射。

- [ ] **步骤 11：建议提交点**

```powershell
git add src/databricks_zh_expert/llm src/databricks_zh_expert/chat src/databricks_zh_expert/api tests
git commit -m "feat: add minimal persisted chat flow"
```

---

### 任务 7：补齐测试隔离、质量门禁和本地运行文档

**文件：**

- 创建或更新：`tests/conftest.py`
- 更新：`README.md`
- 更新：`.env.example`
- 更新：`pyproject.toml`

**接口：**

- 产出：`uv run --locked pytest` 可重复运行，测试数据不会污染开发数据库。
- 产出：README 中从零初始化、启动、迁移、测试、运行和停止服务的完整 PowerShell 命令。

- [ ] **步骤 1：实现测试数据库隔离 fixture**

`tests/conftest.py` 必须：

1. 只读取 `TEST_DATABASE_URL`。
2. 创建测试专用 async engine 和 session factory。
3. 覆盖 FastAPI 的 `get_db` 依赖。
4. 每个集成测试在独立事务中运行并回滚，或在测试前后清理三张业务表。
5. 测试连接拒绝数据库名不以 `_test` 结尾的 URL，避免误删开发数据。
6. 提供 `AsyncClient`，使用 `httpx.ASGITransport(app=app)`。

安全断言必须类似：

```python
assert url.database is not None and url.database.endswith("_test"), (
    "集成测试只能连接名称以 _test 结尾的数据库。"
)
```

- [ ] **步骤 2：补充完整回归测试**

确保测试集合至少包含：

```text
tests/unit/test_config.py
tests/unit/test_health.py
tests/unit/test_chat_service.py
tests/integration/test_migrations.py
tests/integration/test_sessions_api.py
tests/integration/test_messages_api.py
```

测试不得依赖执行顺序，不得读取真实 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`。

- [ ] **步骤 3：完善 README 的本地安装章节**

README 必须按以下顺序写清楚：

1. 已有环境检查。
2. 固定版本 uv 的检查、安装和验证。
3. `Copy-Item .env.example .env`。
4. `.env` 每个字段的用途，明确只有 `.env` 保存真实密钥。
5. 首次执行 `uv lock`，之后执行 `uv sync --locked`。
6. `uv tree --depth 1` 查看直接依赖，`uv tree` 查看完整依赖树。
7. `docker compose config`、`up -d`、`ps`。
8. 开发库和测试库迁移命令。
9. pytest、覆盖率和 ruff 命令。
10. Uvicorn 启动命令和 Swagger 地址 `http://127.0.0.1:8000/docs`。
11. PowerShell API 冒烟测试。
12. `docker compose down` 停止容器但保留数据卷。

README 不要求用户激活 `.venv`；所有命令统一使用 `uv run --locked`，减少 PowerShell execution policy 对虚拟环境激活脚本的影响。

- [ ] **步骤 4：执行完整质量门禁**

用户先确认 Docker 为 healthy，开发库和测试库都已迁移，然后执行：

```powershell
uv lock --check
uv sync --locked
uv run --locked ruff format --check src tests
uv run --locked ruff check src tests
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
```

预期：

1. lockfile 与 `pyproject.toml` 一致。
2. ruff 格式和 lint 均通过。
3. pytest 全部通过。
4. 分支覆盖率不低于 80%。

- [ ] **步骤 5：执行运行状态检查**

```powershell
docker compose ps
uv run --locked alembic current
uv run --locked python -c "from databricks_zh_expert import __version__; print(__version__)"
```

预期：PostgreSQL healthy、Alembic revision 为 `0001_initial`、应用版本为 `0.1.0`。

- [ ] **步骤 6：启动应用并检查端点**

```powershell
uv run --locked uvicorn databricks_zh_expert.main:app --reload --host 127.0.0.1 --port 8000
```

另开 PowerShell：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Start-Process http://127.0.0.1:8000/docs
```

预期：健康检查返回 `status=ok` 和 `database=ok`，Swagger 显示五个阶段 1 API。

- [ ] **步骤 7：停止本地服务**

在 Uvicorn 终端按 `Ctrl+C`，然后执行：

```powershell
docker compose down
```

该命令保留 PostgreSQL 数据卷，下一次启动仍保留会话数据。

- [ ] **步骤 8：建议提交点**

```powershell
git add README.md .env.example pyproject.toml uv.lock tests src
git commit -m "docs: add stage one local development workflow"
```

---

## 阶段 1 验收清单

- [ ] 宿主机只新增 uv，没有全局安装项目 Python 包。
- [ ] `.venv` 位于仓库根目录且被 Git 忽略。
- [ ] `.python-version` 为 `3.12.10`。
- [ ] `pyproject.toml` 中直接依赖都有精确版本。
- [ ] `uv.lock` 已生成并纳入 Git。
- [ ] `.env` 被忽略，`.env.example` 不包含真实密钥。
- [ ] PostgreSQL 18 + pgvector 0.8.5 由 Docker Compose 启动并处于 healthy。
- [ ] 开发数据库和测试数据库分离。
- [ ] Alembic 已启用 vector 扩展并创建三张业务表。
- [ ] `/health` 能检测数据库状态。
- [ ] 会话创建、列表、详情和消息发送 API 可用。
- [ ] 一轮真实聊天会保存两条消息和一条 model_call。
- [ ] 单元测试不连接真实模型。
- [ ] 集成测试拒绝连接非 `_test` 数据库。
- [ ] pytest、覆盖率和 ruff 质量门禁通过。
- [ ] README 包含完整 PowerShell 初始化和运行指令。

## 阶段 1 不包含的内容

1. OpenAI/DeepSeek 白名单和 fallback，留到阶段 2。
2. Prompt Registry 和 Markdown Artifact，留到阶段 3。
3. LlamaIndex、Embedding、知识库表和向量检索，留到阶段 4。
4. Web UI、文件上传、Databricks 连接、SQL 执行和 LangGraph。

## 参考资料

1. [uv Windows 安装](https://docs.astral.sh/uv/getting-started/installation/)
2. [uv 项目环境和锁文件](https://docs.astral.sh/uv/guides/projects/)
3. [uv locking 和 syncing](https://docs.astral.sh/uv/concepts/projects/sync/)
4. [pgvector Docker 标签](https://github.com/pgvector/pgvector#docker)
5. [FastAPI PyPI](https://pypi.org/project/fastapi/)
6. [LiteLLM PyPI](https://pypi.org/project/litellm/)
