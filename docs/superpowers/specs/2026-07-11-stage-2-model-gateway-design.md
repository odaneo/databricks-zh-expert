# 阶段 2：LiteLLM 模型网关设计

## 1. 背景

阶段 1 已完成 FastAPI 聊天接口、会话持久化、单模型 LiteLLM 调用、`model_calls`
记录以及本地 OpenAI Chat Completions 兼容 Trace。当前业务服务仍直接依赖一个由
`DEFAULT_MODEL` 决定的 LiteLLM 客户端，尚不具备业务模型别名、固定白名单、请求级模型选择和
跨供应商 fallback。

阶段 2 在现有聊天链路中加入应用内 `ModelGateway`。该网关只支持 OpenAI 和 DeepSeek，且不
引入 LiteLLM Proxy、独立网关进程或新的基础设施服务。

## 2. 目标

1. Chat API 每次请求可以选择一个固定业务模型别名。
2. 未指定模型时使用环境变量配置的默认模型。
3. 业务代码不直接识别 LiteLLM 的 provider-qualified 模型 ID。
4. 主模型发生可重试错误时，按照全局 fallback 列表顺序切换模型。
5. 每次实际尝试分别写入 `model_calls` 和本地 Trace。
6. API 返回最终实际使用的模型、fallback 状态和尝试次数。
7. 所有配置、fallback 和错误分类都可以在不访问真实模型网络的情况下测试。

## 3. 已确认的产品决策

1. 请求通过业务别名选择模型，不接受 LiteLLM 模型 ID。
2. `model` 字段可选，省略时使用 `DEFAULT_MODEL`。
3. temperature 只从全局环境配置读取，本阶段不允许请求覆盖。
4. fallback 使用全局有序列表，不为每个主模型维护单独列表。
5. 只有超时、限流、连接失败和供应商 5xx 可以触发 fallback。
6. 参数、白名单、密钥、认证、权限和模型不存在等错误不得触发 fallback。
7. 每个模型只尝试一次，不启用 LiteLLM 隐式重试。
8. 同一网关调用中的每次尝试分别持久化并写 Trace。
9. 开发调试默认模型继续使用 `deepseek-v4-flash`。

## 4. 范围

### 4.1 包含

1. 固定模型白名单和模型注册表。
2. 请求级模型选择和模型列表 API。
3. 默认模型、全局 fallback 和全局 temperature 配置。
4. LiteLLM 单次调用适配器。
5. 可重试错误分类和串行 fallback。
6. `model_calls` 尝试分组字段和 Alembic 迁移。
7. Trace 1.1 尝试元数据。
8. OpenAI 与 DeepSeek 各一次真实冒烟验证。

### 4.2 不包含

1. RAG、Embedding、预置知识库和文档检索。
2. Prompt Registry、Artifact 模板和代码生成模块。
3. Responses API、流式输出、工具调用和 LangGraph。
4. LiteLLM Router、LiteLLM Proxy、负载均衡和多部署路由。
5. 动态添加供应商或由用户扩展模型白名单。
6. 模型成本金额换算、预算、限额和计费报表。
7. 前端模型选择器和桌面客户端。

## 5. 模型白名单和注册表

业务 API 只接受以下四个别名：

| 业务别名 | 显示名称 | 供应商 | 默认 LiteLLM ID |
| --- | --- | --- | --- |
| `gpt5.5` | GPT-5.5 | `openai` | `openai/gpt-5.5` |
| `gpt5.4mini` | GPT-5.4 mini | `openai` | `openai/gpt-5.4-mini` |
| `deepseek-v4-flash` | DeepSeek V4 Flash | `deepseek` | `deepseek/deepseek-v4-flash` |
| `deepseek-v4-pro` | DeepSeek V4 Pro | `deepseek` | `deepseek/deepseek-v4-pro` |

别名集合是产品边界，固定在代码的 `ModelAlias` 类型中。环境变量不能添加第五个别名，也不能
将既有别名改成其他供应商。实际 LiteLLM ID 由环境变量注入，使供应商模型标识变化时不需要修改
Chat API。

模型注册表为每个别名提供：

1. 业务别名。
2. 显示名称。
3. 供应商。
4. provider-qualified LiteLLM ID。
5. 供应商 API Key 是否已配置。

## 6. 环境配置

阶段 2 使用以下模型配置：

```dotenv
DEFAULT_MODEL=deepseek-v4-flash
FALLBACK_MODELS=deepseek-v4-flash,gpt5.4mini
DEFAULT_TEMPERATURE=0.2
MODEL_REQUEST_TIMEOUT_SECONDS=60

MODEL_GPT55_ID=openai/gpt-5.5
MODEL_GPT54MINI_ID=openai/gpt-5.4-mini
MODEL_DEEPSEEK_V4_FLASH_ID=deepseek/deepseek-v4-flash
MODEL_DEEPSEEK_V4_PRO_ID=deepseek/deepseek-v4-pro

OPENAI_API_KEY=
DEEPSEEK_API_KEY=
```

`DEFAULT_MODEL` 的含义从阶段 1 的 LiteLLM ID 改为业务别名。`FALLBACK_MODELS` 使用逗号分隔的
业务别名，按配置顺序执行。空字符串表示关闭 fallback。

应用启动时执行纯本地校验：

1. 默认模型必须在固定白名单内。
2. 每个 fallback 别名必须在固定白名单内。
3. fallback 列表去除首尾空白，但重复项属于配置错误，不静默修复。
4. 每个实际模型 ID 的 provider 前缀必须与注册表供应商一致。
5. `DEFAULT_TEMPERATURE` 必须在 `0` 到 `2` 之间。
6. timeout 必须大于零。

启动校验不连接模型供应商，也不要求两组 API Key 都存在。缺少密钥时应用仍可启动，对应模型在
模型列表中显示为未配置，实际请求返回 `model_not_configured`。

## 7. 架构

```text
POST /api/chat/sessions/{session_id}/messages
  -> SendMessageRequest 校验 content 和可选 model 别名
  -> ChatService 保存 user message 并读取最近 20 条消息
  -> ModelGateway 解析请求模型或 DEFAULT_MODEL
  -> ModelGateway 构造去重后的候选序列
  -> LiteLLMTransport 对当前候选执行一次调用
  -> ModelGateway 产出 ModelAttempt
  -> ChatService 立即保存该次 model_call 和 Trace
  -> 成功：保存 assistant message 并返回最终调用信息
  -> 可重试失败：继续下一个 fallback
  -> 不可重试失败或候选耗尽：返回标准错误
```

### 7.1 组件职责

`ModelRegistry`：保存固定别名定义，解析实际模型 ID，提供模型列表和配置状态。

`LiteLLMTransport`：准备实际 Chat Completions 请求，选择对应 API Key，关闭 LiteLLM 内部重试，
执行一次 `litellm.acompletion()`，并归一化成功响应。

`ModelGateway`：解析默认模型、构造候选序列、测量每次耗时、分类错误并依次产出尝试结果。它不
访问数据库、不写文件，也不依赖 FastAPI。

`ChatService`：消费每次尝试，立即写入 Repository 和 Trace；成功时保存 assistant message，失败
时映射为 API 错误。

`ChatRepository`：保存扩展后的 `model_calls` 字段，不理解 fallback 决策。

### 7.2 核心接口

阶段 2 将阶段 1 的单结果 `ModelClient.complete()` 替换为网关运行接口：

```python
class ModelGateway(Protocol):
    def run(
        self,
        messages: list[ModelMessage],
        requested_model: ModelAlias | None,
    ) -> AsyncIterator[ModelAttempt]: ...
```

`ModelAttempt` 至少包含：

```text
invocation_id
requested_model
model_alias
provider
litellm_model
attempt_number
request
response
content
prompt_tokens
completion_tokens
latency_ms
success
retryable
error
```

成功尝试的 `content`、`response` 和 token 字段有值，`error` 为空。失败尝试的 `response` 和
`content` 为空，`error` 使用安全的结构化对象。领域对象不得保存原始异常或 API Key。

使用异步迭代器使 `ChatService` 可以在一次尝试结束后立即持久化，再由网关决定是否继续下一个
候选模型。数据库或 Trace 持久化失败时停止后续 fallback，不产生无法审计的额外模型调用。

## 8. 参数能力

全局 `DEFAULT_TEMPERATURE` 是期望值，不代表所有供应商模型都支持该参数。
`LiteLLMTransport` 使用当前锁定版本提供的 `get_supported_openai_params()` 检查实际模型能力：

1. 支持 `temperature` 时，将其放入实际请求。
2. 不支持时省略该字段，不将参数不兼容误判为供应商故障。
3. Trace 的 `request` 只记录实际发送的字段。

阶段 2 不增加 reasoning effort、thinking mode、top-p 或模型专属参数。相关策略在后续 Prompt 或
任务编排阶段单独设计。

## 9. API 设计

### 9.1 模型列表

新增：

```text
GET /api/models
```

响应示例：

```json
{
  "default_model": "deepseek-v4-flash",
  "fallback_models": ["deepseek-v4-flash", "gpt5.4mini"],
  "models": [
    {
      "alias": "gpt5.5",
      "display_name": "GPT-5.5",
      "provider": "openai",
      "configured": true
    }
  ]
}
```

`configured` 只表示对应供应商 API Key 是否非空，不执行远程可用性检查，不返回密钥内容或实际
LiteLLM ID。

### 9.2 发送消息

现有请求扩展为：

```json
{
  "content": "设计一个每日销售分析工作流",
  "model": "gpt5.5"
}
```

`model` 可选。OpenAPI 将该字段展示为四个业务别名的枚举。非法别名在进入 ChatService 前返回
HTTP 422 和现有 `validation_error` 格式。

成功响应保留阶段 1 字段，并增加：

```json
{
  "session_id": "uuid",
  "user_message": {},
  "assistant_message": {},
  "model_invocation_id": "uuid",
  "model_call_id": "uuid",
  "requested_model": "gpt5.5",
  "used_model": "gpt5.4mini",
  "fallback_used": true,
  "attempt_count": 2
}
```

`requested_model` 在请求省略 `model` 时等于已解析的默认别名。`model_call_id` 指向最终成功尝试的
数据库记录，`model_invocation_id` 用于查询和关联同一网关调用的全部尝试。

## 10. Fallback 状态机

候选序列按以下规则构造：

1. 第一项是请求别名；未提供时使用默认别名。
2. 后续按 `FALLBACK_MODELS` 配置顺序追加。
3. 已出现的别名跳过，保证同一模型最多调用一次。
4. 配置中的重复项已在启动阶段拒绝。

每次尝试后的状态转移：

```text
成功
  -> 停止并返回

可重试失败 + 仍有候选
  -> 继续下一候选

可重试失败 + 无候选
  -> model_fallback_exhausted

不可重试失败
  -> 立即停止并返回对应错误
```

可重试类别：

1. LiteLLM `Timeout`。
2. LiteLLM `RateLimitError` 或 HTTP 429。
3. LiteLLM `APIConnectionError`。
4. LiteLLM `InternalServerError`、`ServiceUnavailableError` 或供应商 HTTP 5xx。

不可重试类别：

1. 非法模型别名。
2. API Key 缺失。
3. `AuthenticationError` 和权限错误。
4. `BadRequestError`、参数错误和内容格式错误。
5. `NotFoundError` 或模型无访问权限。
6. 可解析响应为空或响应结构无效。

错误分类依赖 LiteLLM 的 OpenAI 兼容异常类型和状态码，不解析异常文本。

## 11. 数据库设计

不增加新表。Alembic 迁移扩展 `model_calls`：

| 字段 | 类型 | 约束 | 含义 |
| --- | --- | --- | --- |
| `invocation_id` | UUID | 非空 | 同一请求的模型尝试组 |
| `model_alias` | VARCHAR(100) | 非空 | 本次尝试使用的业务别名或历史模型标识 |
| `attempt_number` | INTEGER | 非空，`>= 1` | 从 1 开始的尝试序号 |
| `retryable` | BOOLEAN | 非空 | 失败是否被分类为可重试 |
| `error_code` | VARCHAR(100) | 可空 | 安全错误代码 |

新增唯一约束：

```text
UNIQUE (invocation_id, attempt_number)
```

迁移已有数据时：

1. `invocation_id` 复制现有 `id`。
2. `attempt_number` 设为 1。
3. `retryable` 设为 false。
4. 已知 provider-qualified 模型 ID 映射到对应业务别名。
5. 无法识别的历史模型将原 `model` 值写入 `model_alias`，保留审计信息。
6. 历史 `error_code` 保持 null，不从自由文本反向猜测。

迁移先增加可空字段并回填，再设置非空约束，保证现有开发数据不丢失。

## 12. Trace 设计

JSONL 顶层结构继续兼容 OpenAI Chat Completions 超集：

```text
schema_version
protocol
trace
request
response
error
```

`schema_version` 从 `1.0` 升级为 `1.1`。`trace` 增加：

```text
invocation_id
requested_model
model_alias
attempt_number
retryable
```

每次模型尝试各写一行。成功行包含完整脱敏响应且 `error=null`；失败行包含安全错误对象且
`response=null`。实际请求中的 provider-qualified `model` 和实际发送的 temperature 必须记录在
`request` 中。

现有日志文件不迁移、不覆盖，旧 1.0 行和新 1.1 行通过 `schema_version` 区分。

## 13. 错误响应

保留现有统一错误响应结构：

```json
{
  "code": "model_fallback_exhausted",
  "message": "模型调用失败，请稍后重试。",
  "details": null
}
```

阶段 2 至少覆盖：

| 错误代码 | HTTP | 说明 |
| --- | --- | --- |
| `validation_error` | 422 | 请求模型别名或其他字段不合法 |
| `model_not_configured` | 503 | 对应供应商 API Key 缺失 |
| `model_authentication_failed` | 503 | API Key 无效或权限不足 |
| `model_request_failed` | 502 | 不可重试的供应商或响应错误 |
| `model_fallback_exhausted` | 502 | 所有可用候选均发生可重试失败 |

HTTP 响应不包含供应商原始错误文本、API Key、请求头或内部 fallback 列表。数据库和 Trace 只记录
错误类型、稳定错误代码和中文安全摘要。

## 14. 事务和持久化顺序

1. 会话校验和 user message 保存沿用阶段 1 行为。
2. 外部模型调用期间不保持数据库事务或连接。
3. 每个 `ModelAttempt` 产出后立即创建一条 `model_calls` 并提交。
4. 数据库记录成功后写对应 Trace。
5. Trace 写入失败只写应用警告，不阻断 fallback 或聊天流程。
6. 成功尝试持久化后再保存 assistant message。
7. 任一数据库持久化失败立即停止，不继续产生无法审计的模型调用。

## 15. 测试策略

### 15.1 单元测试

1. 模型注册表只接受四个业务别名。
2. Settings 校验默认模型、fallback、重复项、provider 前缀、temperature 和 timeout。
3. 请求未指定模型时使用默认别名。
4. 请求指定模型时覆盖默认别名。
5. 候选序列保持顺序、跳过主模型重复项且每个模型最多尝试一次。
6. 可重试错误触发 fallback。
7. 密钥、认证、参数和模型不存在错误立即停止。
8. 全部候选失败时返回 `model_fallback_exhausted`。
9. temperature 只在 LiteLLM 声明支持时发送。
10. 每次尝试都产生独立数据库输入和 Trace 输入。

所有单元测试使用 Fake Transport，不读取真实 API Key、不访问模型网络。

### 15.2 集成测试

1. Alembic upgrade 创建新增字段、约束和索引。
2. 历史 `model_calls` 数据可以完成回填。
3. 消息 API 接受四个别名并保持 model 可选。
4. 非法别名返回 422。
5. 模拟 fallback 后数据库保存同一 `invocation_id` 下的多次尝试。
6. 成功响应返回最终成功 `model_call_id` 和正确的 fallback 元数据。
7. `GET /api/models` 不返回密钥或实际 LiteLLM ID。

### 15.3 真实冒烟

自动测试不调用真实模型。验收阶段分别执行：

1. `deepseek-v4-flash` 一次短请求。
2. `gpt5.4mini` 一次短请求。

真实冒烟验证模型选择、token、数据库记录、Trace 1.1 和密钥脱敏。fallback 只使用 Fake Transport
验证，不通过故意触发供应商故障来测试。

## 16. 文档约束

1. 所有新增设计、计划、注释中的说明和用户可见错误使用中文。
2. 代码标识符、API 字段和环境变量使用英文。
3. `.env.example` 增加阶段 2 配置，不包含真实密钥。
4. README 只更新启动所需的配置步骤，不加入架构说明、测试案例或预期输出长文。
5. 每次修改 Python 代码后运行 Ruff、Pyright、pytest 和覆盖率门禁。

## 17. 完成标准

1. API 可以在同一会话的不同请求中选择不同业务模型。
2. 省略模型时稳定使用配置的默认模型。
3. ChatService 只依赖 `ModelGateway`，不识别供应商或 LiteLLM ID。
4. 主模型发生可重试错误时按全局列表顺序 fallback。
5. 不可重试错误不触发 fallback。
6. 每次尝试均有独立 `model_calls` 和 Trace 1.1 记录。
7. API 明确返回请求模型、实际模型、fallback 状态和尝试次数。
8. 四个模型别名、配置和迁移均有自动测试。
9. OpenAI 与 DeepSeek 各完成一次真实冒烟。
10. Ruff、Pyright、pytest、覆盖率和 Alembic check 全部通过。

## 18. 参考资料

1. [OpenAI GPT-5.5](https://developers.openai.com/api/docs/models/gpt-5.5)
2. [OpenAI GPT-5.4 mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
3. [DeepSeek 模型列表](https://api-docs.deepseek.com/api/list-models)
4. [DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion)
5. [LiteLLM Python SDK 和异常映射](https://docs.litellm.ai/)
