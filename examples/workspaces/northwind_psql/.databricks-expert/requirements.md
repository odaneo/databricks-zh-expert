# 项目需求

## 业务目标

以 Northwind PostgreSQL 源 Schema 为项目事实，为 AWS Databricks 设计一套可评审但不自动执行的销售分析方案。方案需要支持每日销售、客户价值、商品与品类表现、员工销售表现和配送表现，并明确区分源事实、设计假设与待确认事项。

## 源系统

源系统是部署在 Amazon RDS for PostgreSQL 的 Northwind 数据库。项目可依赖的源表、字段、主键和外键只来自 `source-schema/northwind-schema.sql`；该文件未定义的字段不得当成事实使用。

## 期望数据产品

需要五类数据产品：每日销售、客户价值、商品与品类表现、员工销售表现、配送表现。这里仅固定分析目标和已确认指标口径，不预定义 Databricks Catalog、Schema、目标表名或目标字段。

## 摄取需求

基准摄取链路固定为 RDS PostgreSQL → AWS DMS → S3 Parquet → Auto Loader。AWS DMS 负责全量与 CDC 文件落地，Databricks 使用 Auto Loader 增量摄取 S3 Parquet；不采用 Preview 功能。具体 DMS 元数据列、S3 路径、Checkpoint 路径和触发间隔必须参数化或列为待确认项。

## 数据量与 SLA 假设

Northwind Schema 不提供生产数据量、峰值、增量比例、恢复目标或服务等级，因此不得虚构数值。每日批次完成时间、数据新鲜度、允许延迟、重跑窗口和各数据产品 Owner 均待业务与平台团队确认。

## 治理与安全

客户、员工和供应商表含联系人、电话与地址类字段，应按潜在个人或商业敏感信息治理。方案需要遵循 Unity Catalog 最小权限、按用途发布字段、血缘与审计原则；具体分类等级、脱敏规则和授权主体待确认。

## 技术约束

云平台固定为 AWS，目标平台为 Databricks。Agent 不连接 RDS、AWS 或 Databricks，不执行生成的 SQL、PySpark、Notebook 或工作流；所有目标层设计和代码都属于人工确认前的提案。

## 待确认事项

需要确认 DMS 任务模式与元数据格式、S3 Bucket 与目录规范、Catalog 与 Schema 命名、调度时区、数据保留期、SLA、Owner、告警渠道、成本预算，以及销售指标是否只统计已发货订单。
