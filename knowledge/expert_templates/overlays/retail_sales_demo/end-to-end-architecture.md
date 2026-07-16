---
id: retail.end_to_end_architecture
name: AWS 零售端到端模拟架构
summary: 组合 S3、DMS、Kinesis、Lakeflow Pipelines、Delta 和 Unity Catalog 的零售基准架构。
version: 1.0.0
kind: blueprint
category: pipeline
layer: retail_sales_demo
profile: retail_sales_demo
cloud: aws
prompt_names:
  - databricks_qa
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - retail
  - architecture
  - lakeflow
  - aws
extends: pipeline.lakeflow_sdp
is_mock: true
official_refs:
  - https://docs.databricks.com/aws/en/ldp/concepts
  - https://docs.databricks.com/aws/en/ldp/best-practices
  - https://docs.databricks.com/aws/en/connect/streaming/kinesis
---

# AWS 零售端到端模拟架构

## 适用场景

本资产把 `retail_sales_demo` 模拟项目的数据源和服务目标映射为 Databricks on AWS 逻辑架构，扩展通用 Lakeflow 声明式管道蓝图。它描述组件职责，不证明环境已经建成或达到性能目标。

## 逻辑数据流

```text
S3 POS 与供应商日批 -----------------> Auto Loader -----------+
RDS PostgreSQL -> AWS DMS -> S3 Parquet -> Auto Loader ------+--> Lakeflow Spark Declarative Pipelines
Kinesis order/payment/behavior -----> Structured Streaming ---+             |
                                                                            v
                                                                 Bronze -> Silver -> Gold
                                                                            |
                                                                            v
                                                              Lakeflow Jobs 与 ops 监控
```

Delta 表由 Unity Catalog 管理，并按环境放入 `retail_dev`、`retail_test`、`retail_prod`。每个 Catalog 使用 `bronze`、`silver`、`gold`、`ops` Schema，环境之间不共享存储位置、运行身份或 checkpoint。

## 组件设计决策

1. S3 日批与 DMS 落地文件使用 Auto Loader，但各自保留独立 schema、checkpoint 和故障隔离边界。
2. Kinesis 采用 Structured Streaming 进入 Bronze，事件解析与 Silver 业务规则分层处理。
3. Lakeflow Spark Declarative Pipelines 管理 Bronze 到 Gold 的声明式依赖、质量规则和增量刷新。
4. Lakeflow Jobs 只负责跨 Pipeline 的调度、依赖、通知和批次验收，不把数据转换散落到编排层。
5. `ops` 保存运行指标、对账结果和隔离记录；不得保存明文联系方式或访问凭据。

## 风险与人工确认项

- 核对 AWS DMS 产生的操作字段、文件切分和乱序条件，不能把对象存储到达顺序当作事务顺序。
- 核对 Kinesis 峰值、迟到事件与 checkpoint 恢复测试，确认 5 分钟目标的容量余量。
- 核对日批 07:00 完成和 Gold 07:30 可查询之间的发布、质量阻断与回退窗口。
- 生产部署前重新评估网络、身份、加密、保留、灾备和成本，不使用模拟容量作采购依据。
