---
id: retail.project_context
name: AWS 零售销售项目上下文
summary: 固定零售销售 Demo 的业务范围、AWS 数据源、平台边界和基线 SLA。
version: 1.1.0
kind: blueprint
category: delivery
layer: retail_sales_demo
profile: retail_sales_demo
cloud: aws
prompt_names:
  - databricks_qa
  - sql_generation
  - pyspark_generation
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - retail
  - aws
  - project
  - project-context
extends: null
official_refs:
  - https://docs.databricks.com/aws/en/lakehouse-architecture/reference
  - https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Target.S3.html
---

# AWS 零售销售项目上下文

## 适用场景

本资产仅适用于 `retail_sales_demo` 项目，用于在需求不完整时补充一致的项目背景。所有系统、数据、SLA 和角色均为设计假设，不代表任何实际企业，也不表示相关资源已经部署。

## 业务目标与范围

- 在 Databricks on AWS 建设销售分析平台，统一门店日批、主数据 CDC 和电商实时事件。
- 服务每日销售分析、商品表现分析、库存健康分析、客户与渠道分析四个 Gold 数据产品。
- 只输出架构、代码和交付草案，不连接或操作 AWS、Databricks 及源数据库。
- 不包含 BI Dashboard、源系统改造、生产容量结论或未经确认的成本数字。

## 数据源假设

| 来源 | 项目假设 | 接入基线 |
| --- | --- | --- |
| Amazon S3 | POS 日销售、供应商商品文件 | 每日文件由 Auto Loader 摄取 |
| RDS PostgreSQL | customer、product、store、inventory | AWS DMS full load + CDC 到 S3 Parquet，再由 Auto Loader 摄取 |
| Kinesis | order、payment、customer_behavior 事件 | Structured Streaming 持续处理 |

## 基线 SLA

- Kinesis 事件端到端延迟不超过 5 分钟。
- RDS CDC 在 15 分钟内进入 Bronze。
- POS 日批假设每日 05:00 到达，07:00 前完成 Gold 更新。
- Gold 报表每日 07:30 前可查询，核心任务基线月度成功率目标为 99.5%。

## 设计决策与确认项

默认采用 `retail_dev`、`retail_test`、`retail_prod` Catalog，以及 `bronze`、`silver`、`gold`、`ops` Schema。进入实施前必须重新确认数据量、保留期、恢复目标、时区、节假日批次和 SLA；用户明确提供的约束优先于本项目基线。
