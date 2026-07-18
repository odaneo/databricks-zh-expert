---
id: pipeline.lakeflow_sdp
name: Lakeflow 声明式管道蓝图
summary: 使用 Lakeflow Spark Declarative Pipelines 组织稳定的流表、物化视图和质量规则。
version: 1.1.0
kind: blueprint
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
  - lakeflow
  - pipelines
  - streaming-table
  - materialized-view
extends: null
official_refs:
  - https://docs.databricks.com/aws/en/ldp/concepts
  - https://docs.databricks.com/aws/en/ldp/best-practices
  - https://docs.databricks.com/aws/en/ldp/developer/python-ref
---

# Lakeflow 声明式管道蓝图

## 适用场景

适用于希望由 Lakeflow Spark Declarative Pipelines 管理数据集依赖、增量刷新、质量事件和运行可观测性的 ETL。外部系统编排、一次性分析或需要任意副作用的任务应放在 Lakeflow Jobs 等边界中。

## 数据集设计

- 流表用于追加式接入和需要逐批处理的新数据。
- 物化视图用于可声明为查询、由平台维护刷新结果的转换与聚合。
- 临时视图只封装管道内部逻辑，不作为下游稳定契约。

## 设计决策

1. 数据集函数只返回 DataFrame，不在定义函数中执行写文件、启动流或发送外部请求等副作用。
2. 把期望规则分为观测、丢弃和阻断三档，并为规则名称、责任人和处置方式建立清单。
3. 按数据域和发布节奏划分管道；不要仅为减少管道数量而放大故障范围。
4. 从 event log、数据质量结果和更新历史定义监控，不依赖 Notebook 文本输出判断成功。

## 风险与人工确认项

- 确认目标数据集类型、刷新语义和源是否满足增量处理条件。
- 确认使用的 API 在目标 Runtime 与 workspace 中稳定可用。
- 确认全量刷新、回补和 schema 变更的审批边界。
