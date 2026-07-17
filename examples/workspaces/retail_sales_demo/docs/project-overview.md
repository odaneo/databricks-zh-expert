# AWS 零售销售分析 Mock 项目

这是贯穿 Databricks 中文专家 Agent 的零售销售模拟项目。全部系统、表、字段、路径、SLA 和容量都是设计
假设，不代表任何真实企业，也不表示 AWS 或 Databricks 资源已经创建、部署或运行。

## 业务目标

项目统一门店 POS 日批、RDS PostgreSQL 主数据与库存 CDC，以及 Kinesis 电商事件，形成以下四个 Gold
数据产品：

1. 每日销售分析 `gold.daily_sales`。
2. 商品表现分析 `gold.product_performance`。
3. 库存健康分析 `gold.inventory_health`。
4. 客户与渠道分析 `gold.customer_channel`。

## Mock 数据来源

| 来源 | 模拟内容 | 接入基线 |
| --- | --- | --- |
| Amazon S3 | POS 销售明细日批 Parquet | 每日 05:00 后由 Auto Loader 摄取 |
| RDS PostgreSQL | customer、product、store、inventory | AWS DMS full load + CDC 到 S3 Parquet，再由 Auto Loader 摄取 |
| Kinesis | 订单、支付、客户行为事件 | Structured Streaming 持续摄取 |

RDS CDC 以 `_dms_op` 和 `_dms_commit_ts` 表达变更语义；Kinesis 以 `event_id` 和 `event_ts`
表达事件身份与发生时间。对象存储文件必须保留 `_ingest_ts`、`_source_file` 和 `_rescued_data`。

## 分层与环境

- Bronze 保存可追溯原始数据和摄取控制字段，不直接承担业务口径。
- Silver 完成类型统一、去重、CDC 合并、订单行统一、主数据关联与 PII 脱敏。
- Gold 发布四个固定粒度的数据产品，不暴露原始姓名、邮箱、手机号或地址。
- 环境 Catalog 固定为 `retail_dev`、`retail_test`、`retail_prod`，每个 Catalog 使用独立的
  `bronze`、`silver`、`gold` 和 `ops` Schema。

## Mock SLA 与人工确认

- Kinesis 事件端到端延迟目标为 5 分钟。
- RDS CDC 进入 Bronze 的延迟目标为 15 分钟。
- POS 日批假设每日 05:00 到达，Gold 在 07:00 前完成更新并在质量门通过后于 07:30 前可查询。
- 核心作业的 99.5% 月度成功率只是 Mock 目标。

进入真实项目前必须重新确认数据量、文件命名、源主键、时区、迟到边界、保留期、恢复目标、指标口径、
PII 策略和所有 SLA。本工作区只为 Agent 生成文档与代码草稿提供上下文，Agent 不执行其中任何代码。
