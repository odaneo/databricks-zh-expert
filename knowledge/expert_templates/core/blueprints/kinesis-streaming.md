---
id: ingestion.kinesis_streaming
name: Kinesis 流式摄取蓝图
summary: 设计 Amazon Kinesis 事件进入 Databricks Structured Streaming 的可靠摄取边界。
version: 1.0.0
kind: blueprint
category: ingestion
layer: core
profile: null
cloud: aws
prompt_names:
  - databricks_qa
  - pyspark_generation
  - workflow_design
  - proposal_generation
tags:
  - kinesis
  - structured-streaming
  - checkpoint
  - events
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/connect/streaming/kinesis
  - https://docs.databricks.com/aws/en/structured-streaming/checkpoints
---

# Kinesis 流式摄取蓝图

## 适用场景

适用于事件持续写入 Amazon Kinesis、需要分钟级或更低延迟进入 Bronze 的场景。若业务允许固定窗口批量处理，应同时评估按批摄取能否降低常驻计算和运维复杂度。

## 输入与前置条件

- 固定 stream、region、事件 envelope、分区键语义和生产者重试策略。
- 使用受控运行身份访问 Kinesis，认证配置不写入 Notebook 或模板正文。
- 为每条查询使用独立 checkpoint，并记录 query 与 checkpoint 的对应关系。

## 设计决策

1. Bronze 同时保留原始二进制载荷和 Kinesis 元数据，解析结果放在显式字段中。
2. 以 event id 设计幂等去重；`sequenceNumber` 仅作为来源元数据，不能替代跨分区业务顺序。
3. 有状态计算必须定义 watermark、状态保留和迟到事件处置，避免状态无限增长。
4. shard 调整、消费者模式和触发间隔依据积压与处理时长测量，不写死通用吞吐值。

## 风险与人工确认项

- 重新创建 stream 或切换 stream name 与 ARN 时，确认是否需要新的 checkpoint。
- 确认坏事件、未知 schema、重放和下游不可用时的隔离策略。
- 确认监控至少包含输入速率、处理速率、batch duration、积压和状态大小。
