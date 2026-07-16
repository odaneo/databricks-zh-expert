---
id: decision.pipeline_dataset_type
name: Pipeline 数据集类型选择指南
summary: 在流表、物化视图和临时视图之间按更新语义与消费契约选型。
version: 1.0.0
kind: decision_guide
category: pipeline
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - pyspark_generation
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - streaming-table
  - materialized-view
  - temporary-view
  - lakeflow
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/ldp/best-practices
  - https://docs.databricks.com/aws/en/ldp/concepts
---

# Pipeline 数据集类型选择指南

## 适用场景

用于 Lakeflow Spark Declarative Pipelines 设计时确定数据集类型。选型应从源更新方式、转换语义和下游读取契约出发，而不是按 Bronze、Silver、Gold 名称机械对应。

## 选择条件

- 流表：源是追加式流或文件增量，希望每条新记录只处理一次，并持续保留结果。
- 物化视图：转换可以表达为查询，希望平台维护预计算结果，适合聚合、关联和消费视图。
- 临时视图：只在当前管道内复用逻辑，不需要持久化，也不向外提供数据契约。

## 决策步骤

1. 写明源是否追加、是否更新历史记录，以及删除如何表达。
2. 写明转换是否需要有状态操作、全局聚合或多源关联。
3. 写明下游需要表级契约、刷新后结果，还是仅管道内部中间结果。
4. 用少量真实分区验证刷新范围、延迟、资源和 schema 变化行为。

## 不适用与人工确认

- 需要任意外部副作用、手工循环或非 DataFrame 返回值时，不应塞入数据集定义函数。
- 不能确认增量语义时，先选择容易验证的方案并记录重算成本。
- API 与数据集能力必须按目标 Runtime 和 workspace 实际验证后确定。
