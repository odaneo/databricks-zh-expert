---
id: retail.source_contracts
name: AWS 零售数据源模拟契约
summary: 定义 S3 日批、DMS CDC 和 Kinesis 事件的输入粒度、控制字段与异常边界。
version: 1.1.0
kind: deliverable
category: ingestion
layer: retail_sales_demo
profile: retail_sales_demo
cloud: aws
prompt_names:
  - databricks_qa
  - ddl_generation
  - mapping_generation
  - sql_generation
  - pyspark_generation
  - notebook_generation
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - retail
  - source-contract
  - dms
  - kinesis
extends: null
is_mock: true
official_refs:
  - https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader
  - https://docs.databricks.com/aws/en/connect/streaming/kinesis
  - https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Target.S3.html
---

# AWS 零售数据源模拟契约

## 适用场景

本资产为 `retail_sales_demo` 模拟项目的数据源交付契约，用于生成摄取设计、表定义和核对清单。字段与频率均为占位假设，实施前必须由源系统负责人确认。

## 交付契约

| 来源 | 对象与粒度 | 到达与格式 | 必要控制信息 |
| --- | --- | --- | --- |
| S3 POS | `pos_sales`，一行一个门店销售明细 | 每日 05:00，Parquet | `business_date`、`store_id`、`receipt_id`、文件名、摄取时间 |
| S3 供应商 | `supplier_product`，一行一个供应商商品版本 | 每日文件，Parquet | `supplier_id`、`product_id`、`effective_at`、文件校验值 |
| RDS PostgreSQL | `customer`、`product`、`store`、`inventory` | AWS DMS full load + CDC 到 S3 Parquet | 操作类型、提交时间、主键、DMS 批次标识 |
| Kinesis | `order`、`payment`、`customer_behavior`，一条记录一个事件 | 持续 JSON 事件 | `event_id`、`event_type`、`event_time`、分区键、生产时间 |

## Schema 与质量决策

1. Auto Loader 为 S3 Parquet 保留独立 checkpoint 与 schema 位置；不同来源不能共用状态目录。
2. Bronze 保留源记录和摄取元数据，不因业务字段缺失而覆盖原始值；无法解析的数据进入隔离表。
3. CDC 按主键、提交时间和操作类型判定顺序，删除事件必须显式保留，不从文件到达顺序推断。
4. Kinesis 以 `event_id` 去重并以 `event_time` 处理迟到事件；允许迟到范围需要业务确认。
5. 客户联系方式属于虚构 PII，仅可进入受限 Bronze，不得写入普通运行日志。

## 人工检查项

- [ ] 确认每张 RDS 表的主键、CDC 起点、删除语义与 schema 变更流程。
- [ ] 确认 S3 文件命名、重送规则、空文件、补档和重复文件处理方式。
- [ ] 确认 Kinesis 分区键、峰值吞吐、事件版本和生产者重试语义。
- [ ] 确认所有时间字段的时区，以及 15 分钟 CDC 和 5 分钟事件 SLA 的测量起止点。
