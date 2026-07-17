# Databricks 中文专家 Agent

Databricks 顾问型 Agent Demo，只提供问答、文档检索、代码草稿和工作流设计建议，不直接操作 Databricks。

## 1. 准备环境

安装以下环境：

1. Python 3.12.10
2. Docker Desktop 和 Docker Compose
3. Git
4. Windows PowerShell

## 2. 安装 uv

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/0.11.28/install.ps1 | iex"
```

重新打开 PowerShell：

```powershell
uv --version
```

## 3. 初始化项目

在仓库根目录执行：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv sync --locked
uv tree --depth 1
uv run --locked python --version
```

## 4. 配置环境变量

编辑 `.env`，确认 `.env.example` 中的全部配置，并填写需要使用的 `OPENAI_API_KEY` 和 `DEEPSEEK_API_KEY`。

`DEFAULT_MODEL` 和 `FALLBACK_MODELS` 使用 `.env.example` 中的业务别名；四个固定 LiteLLM 模型 ID 由代码模型目录统一维护。

## 5. 启动数据库

```powershell
docker compose config
docker compose up -d postgres
docker compose exec postgres bash /docker-entrypoint-initdb.d/01-initialize-app-schema.sh
docker compose exec postgres bash /docker-entrypoint-initdb.d/02-initialize-test-database.sh
docker compose ps
```

## 6. 验证数据库

```powershell
docker compose exec postgres psql -U databricks_agent -d databricks_agent -c "SHOW search_path;"
docker compose exec postgres psql -U databricks_agent -d databricks_agent -c "SELECT e.extname, n.nspname AS schema_name FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'vector';"
docker compose exec postgres psql -U databricks_agent -d databricks_agent_test -c "SHOW search_path;"
```

## 7. 执行数据库迁移

迁移开发数据库：

```powershell
uv run --locked alembic upgrade head
uv run --locked alembic current
```

迁移测试数据库：

```powershell
$env:DATABASE_URL="postgresql+psycopg://databricks_agent:databricks_agent_dev@localhost:5432/databricks_agent_test"
uv run --locked alembic upgrade head
Remove-Item Env:DATABASE_URL
```

写入可重复生成的开发演示数据：

```powershell
uv run --locked python -m databricks_zh_expert.devtools.seed_demo_data
```

初始化专家模板索引：

```powershell
uv run databricks-zh-expert-templates sync
```

## 8. 运行项目检查

```powershell
uv run --locked alembic check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked pyright
uv run --locked pytest --cov=databricks_zh_expert --cov-report=term-missing
```

## 9. 构建预置知识库

```powershell
uv run --locked databricks-zh-expert-kb sync
uv run --locked databricks-zh-expert-kb status
```

## 10. 启动 FastAPI

```powershell
uv run --locked databricks-zh-expert
```
打开 http://127.0.0.1:8000/docs

## 11. 停止数据库

停止容器并保留数据卷：

```powershell
docker compose down
```
