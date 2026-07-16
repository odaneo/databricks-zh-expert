---
id: decision.incremental_replay_backfill
name: 增量、重放与回填选择指南
summary: 区分日常增量、事件重放和历史回填，并固定幂等与发布边界。
version: 1.0.0
kind: decision_guide
category: workflow
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - incremental
  - replay
  - backfill
  - idempotency
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/structured-streaming/checkpoints
  - https://docs.databricks.com/aws/en/tables/history
---

# 增量、重放与回填选择指南

## 适用场景

用于区分正常增量处理、从原始事件重新消费、以及按业务日期重算历史结果。三者的触发原因、输入范围和发布风险不同，不应共用一个模糊的“重新跑”按钮。

## 选择条件

- 增量：消费尚未处理的新输入，沿用既有 checkpoint 或高水位。
- 重放：从保留的原始事件重新构建下游状态，通常需要独立运行标识与隔离输出。
- 回填：修复指定业务时间范围或新增历史口径，必须限制扫描和覆盖范围。

## 决策步骤

1. 记录原因、源范围、业务日期、目标对象、代码版本和预期差异。
2. 证明写入幂等，或在隔离表完成对账后再原子发布。
3. 不随意删除生产 checkpoint；需要新语义时使用新的 checkpoint 和明确切换计划。
4. 对账至少包含记录数、主键重复、关键指标、质量规则和下游影响。

## 不适用与人工确认

- 原始数据已过保留期时，不能声称可以完整重放。
- 回填与在线增量同时写同一范围前，必须确认并发冲突策略。
- 发布后必须保存运行参数、差异结果和回滚入口。
