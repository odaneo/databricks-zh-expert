# 阶段 1：项目初始化与最小聊天后端设计

## 1. 目标

阶段 1 建立一个可重复安装、可启动、可迁移、可测试的 Python 后端工程，并完成最小聊天闭环：创建会话、保存用户消息、调用一个默认模型、保存模型回复、记录模型调用结果。

本阶段不实现完整模型网关、RAG、Prompt Registry、Markdown Artifact 管理、前端或 LangGraph。这些能力分别由后续阶段负责。

## 2. 已确认约束

1. 宿主机操作系统按 Windows PowerShell 编写命令。
2. Python 固定使用 3.12.10。
3. 用户本地已有 Python 3.12.10 和 Docker，其他工具默认没有。
4. Python 项目依赖全部安装到仓库根目录的 `.venv`，不得写入全局 Python。
5. 使用 uv 0.11.28 管理 `.venv`、依赖和锁文件。
6. 直接依赖及其版本在 `pyproject.toml` 中可见，完整依赖树在 `uv.lock` 中可追溯。
7. `uv.lock`、`.python-version` 和 `.env.example` 提交到 Git；`.venv` 和 `.env` 不提交。
8. PostgreSQL 不安装到宿主机，使用 Docker Compose 启动。
9. Docker 镜像固定为 `pgvector/pgvector:0.8.5-pg18-bookworm`。
10. FastAPI 在宿主机运行，只把 PostgreSQL 放入 Docker。
11. 所有说明文档和面向用户的文本使用中文；Python 标识符、API 字段和日志字段使用英文。

## 3. 初始化方案比较

### 方案 A：uv 项目模式，采用方案

使用 `.python-version` 固定 Python，使用 `pyproject.toml` 声明直接依赖，使用 `uv.lock` 锁定完整依赖树，使用 `uv sync` 创建项目内 `.venv`。

优点是宿主机只增加一个 uv 工具，依赖不会污染全局 Python，锁文件跨平台且便于检查。缺点是团队成员需要先安装 uv。

### 方案 B：Python venv + pip

只依赖 Python 自带工具，额外环境要求最低。缺点是需要额外维护 `requirements.in`、`requirements.txt` 和开发依赖文件，锁定、升级和依赖树查看都更分散。

### 方案 C：Poetry

也能提供项目环境和锁文件，但工具本身较重，配置和命令比当前 Demo 所需复杂。

最终选择方案 A。

## 4. 本地环境边界

### 4.1 宿主机需要安装

1. Python 3.12.10。
2. Docker Desktop，并能够执行 `docker compose`。
3. uv 0.11.28。
4. Git，仓库已经存在，因此不作为本阶段新增安装项。

### 4.2 宿主机不需要安装

1. PostgreSQL。
2. pgvector。
3. Alembic。
4. FastAPI、LiteLLM、pytest、ruff 等 Python 包。
5. Node.js、Java、Databricks CLI。

这些 Python 包全部由 uv 安装到 `.venv`，数据库由 Docker 提供。

## 5. 依赖策略

阶段 1 的直接运行依赖固定为：

| 包 | 版本 | 用途 |
| --- | --- | --- |
| `fastapi` | `0.139.0` | HTTP API |
| `uvicorn[standard]` | `0.51.0` | 本地 ASGI 服务 |
| `pydantic` | `2.13.4` | 请求、响应和领域数据校验 |
| `pydantic-settings` | `2.14.2` | 环境变量配置 |
| `python-dotenv` | `1.2.2` | 读取 `.env` |
| `sqlalchemy[asyncio]` | `2.0.51` | 异步 ORM 和数据库访问 |
| `psycopg[binary]` | `3.3.4` | PostgreSQL 驱动 |
| `alembic` | `1.18.5` | 数据库迁移 |
| `litellm` | `1.91.1` | 阶段 1 的最小模型调用适配器 |

构建后端固定使用 `hatchling==1.31.0`，写在 `pyproject.toml` 的 `[build-system]` 中。

开发依赖固定为：

| 包 | 版本 | 用途 |
| --- | --- | --- |
| `pytest` | `9.1.1` | 测试框架 |
| `pytest-asyncio` | `1.4.0` | 异步测试 |
| `httpx` | `0.28.1` | FastAPI API 测试客户端 |
| `pytest-cov` | `7.1.0` | 覆盖率报告 |
| `ruff` | `0.15.21` | 格式化和静态检查 |
| `pyright` | `1.1.411` | Pylance 等价的项目级类型检查 |

阶段 1 不安装 LlamaIndex 和 Python `pgvector` 包。Docker 数据库已包含 pgvector 扩展，初始迁移只执行 `CREATE EXTENSION IF NOT EXISTS vector`；Python 侧真正定义向量字段时，再在阶段 4 加入 `pgvector` 包。

## 6. 工程结构

```text
databricks-zh-expert/
  src/
    databricks_zh_expert/
      __init__.py
      main.py
      api/
        health.py
        chat.py
        dependencies.py
      core/
        config.py
        errors.py
        logging.py
      db/
        base.py
        session.py
        models.py
      chat/
        schemas.py
        repository.py
        service.py
      llm/
        client.py
        litellm_client.py
  tests/
    conftest.py
    unit/
    integration/
  alembic/
    versions/
  docker/
    postgres/
      init/
  docs/
  scripts/
  .env.example
  .python-version
  alembic.ini
  docker-compose.yml
  pyproject.toml
  uv.lock
  README.md
```

采用 `src` 布局，Python 包名为 `databricks_zh_expert`，避免使用含义过泛的 `app` 包名，并避免测试时意外从仓库根目录导入未安装代码。

## 7. 配置与秘密管理

`.env.example` 提供完整键名和本地开发示例值，用户复制为 `.env` 后修改。`.env` 已加入 `.gitignore`。

阶段 1 配置分为：

1. 应用配置：`APP_NAME`、`APP_ENV`、`APP_HOST`、`APP_PORT`、`LOG_LEVEL`。
2. 数据库配置：Compose 使用 `POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_PORT`；应用只读取 `DATABASE_URL` 和 `POSTGRES_SCHEMA`。
3. 模型配置：`DEFAULT_MODEL`、`MODEL_REQUEST_TIMEOUT_SECONDS`、`OPENAI_API_KEY`、`DEEPSEEK_API_KEY`。

应用运行所读取的 `APP_NAME`、`APP_ENV`、`APP_HOST`、`APP_PORT`、`LOG_LEVEL`、`MODEL_REQUEST_TIMEOUT_SECONDS`、`DEFAULT_MODEL`、`DATABASE_URL` 和 `POSTGRES_SCHEMA` 都是必填部署配置，不在 Python 代码中提供回退值。`pydantic-settings` 在应用启动时进行类型和必填项校验；操作系统环境变量优先于 `.env`。API 密钥允许为空，因此健康检查和数据库功能可以在没有模型密钥时启动；调用聊天接口时，如果当前模型所需密钥为空，返回明确的 `model_not_configured` 错误。

应用使用可注入的 `create_app(settings)` 工厂，不在模块导入时创建全局 FastAPI 实例。项目启动命令通过 `run()` 读取 `APP_HOST`、`APP_PORT` 和 `LOG_LEVEL` 并以 Uvicorn factory 模式启动，避免运行参数同时散落在代码、`.env` 和命令行中。

## 8. Docker 与数据库

Docker Compose 只启动一个 `postgres` 服务，使用固定版本镜像 `pgvector/pgvector:0.8.5-pg18-bookworm`、命名数据卷和健康检查。宿主机 FastAPI 通过 `localhost:5432` 访问数据库。

Compose 初始化脚本额外创建 `databricks_agent_test` 测试数据库。开发数据库和测试数据库分离，避免测试删除开发数据。

初始 Alembic 迁移负责：

1. 启用 `vector` 扩展。
2. 创建 `sessions`。
3. 创建 `messages`。
4. 创建 `model_calls`。
5. 创建必要外键、检查约束和索引。

## 9. 应用结构与数据流

FastAPI 使用应用工厂创建实例。路由不直接访问 LiteLLM 或 SQLAlchemy，而是调用 `ChatService`。

最小聊天流程：

```text
POST message
  -> 校验会话存在和消息内容
  -> 保存 user message 并提交事务
  -> 加载最近 20 条会话消息
  -> 调用 ModelClient
  -> 成功：保存 assistant message 和成功 model_call
  -> 失败：保存失败 model_call，返回标准错误
```

外部模型调用期间不保持数据库事务，避免网络等待占用数据库连接。

`ModelClient` 定义窄接口，生产实现使用 LiteLLM，测试实现使用内存 Fake。阶段 2 可以在不修改 Chat API 和 ChatService 的前提下替换为完整 ModelGateway。

## 10. API 范围

阶段 1 提供：

```text
GET  /health
POST /api/chat/sessions
GET  /api/chat/sessions
GET  /api/chat/sessions/{session_id}
POST /api/chat/sessions/{session_id}/messages
```

不提供删除会话、修改标题、流式输出、模型选择、文件上传和鉴权。

## 11. 错误处理

统一错误响应包含 `code`、`message` 和可选 `details`。阶段 1 至少覆盖：

1. `session_not_found`：会话不存在，HTTP 404。
2. `validation_error`：请求不合法，HTTP 422。
3. `model_not_configured`：缺少模型密钥，HTTP 503。
4. `model_request_failed`：模型调用失败，HTTP 502。
5. `database_unavailable`：健康检查无法访问数据库，HTTP 503。

日志写到标准输出，不写本地日志文件，不记录 API 密钥或完整 Prompt。模型调用的 provider、model、耗时、token 数和错误摘要写入 `model_calls`。

## 12. 测试策略

1. 配置单元测试验证 `.env` 加载、缺省值和密钥脱敏。
2. 健康检查测试验证数据库正常和不可用两种状态。
3. Repository 集成测试使用 `databricks_agent_test`。
4. ChatService 单元测试使用 Fake ModelClient，不访问真实模型网络。
5. API 集成测试覆盖创建会话、查询会话、发送消息和 404。
6. 迁移验证执行 Alembic upgrade、检查三张业务表和 `vector` 扩展。
7. 测试和静态检查统一通过 `uv run --locked` 执行。

## 13. 用户本地执行边界

后续实施时，Codex 负责创建和修改项目文件，不主动替用户启动 Docker 或安装依赖。用户按 README 执行：

1. 安装并验证 uv。
2. 复制 `.env.example` 为 `.env` 并填写模型密钥。
3. 执行 `uv lock` 和 `uv sync --locked`。
4. 执行 `docker compose up -d`。
5. 执行 Alembic 迁移。
6. 启动 FastAPI。
7. 执行测试、ruff 和 Pyright。

## 14. 完成标准

1. 新机器只安装 Docker、Python 3.12.10 和 uv 即可初始化项目。
2. `uv sync --locked` 只在项目 `.venv` 安装依赖。
3. `docker compose up -d` 能启动健康的 PostgreSQL + pgvector。
4. `alembic upgrade head` 能创建扩展和三张业务表。
5. `/health` 同时报告应用和数据库状态。
6. 五个阶段 1 API 可通过 Swagger 或 HTTP 客户端调用。
7. 一轮聊天能持久化 user message、assistant message 和 model_call。
8. 没有真实模型密钥时，测试仍可全部运行。
9. `pytest`、覆盖率、ruff 和 Pyright 检查通过。
10. README 包含从环境检查到关闭 Docker 的完整 PowerShell 命令。

## 15. 版本来源

依赖版本于 2026-07-10 根据各项目 PyPI 页面确认。uv 安装和锁文件行为参考 Astral 官方文档；PostgreSQL/pgvector 镜像标签参考 pgvector 官方仓库。
