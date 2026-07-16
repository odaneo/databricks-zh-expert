---
id: decision.ingestion_mode
name: 数据摄取模式选择指南
summary: 在批处理、文件增量、CDC 和事件流之间按业务语义选择摄取模式。
version: 1.0.0
kind: decision_guide
category: ingestion
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - batch
  - cdc
  - streaming
  - decision
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/ingestion/
  - https://docs.databricks.com/aws/en/structured-streaming/concepts
---

# 数据摄取模式选择指南

## 适用场景

用于需求阶段判断应采用定时批处理、对象存储文件增量、数据库 CDC 还是消息流。选择依据是源系统能力与业务时效，不以“流处理更先进”作为结论。

## 选择条件

| 模式 | 优先选择条件 | 主要代价 |
| --- | --- | --- |
| 定时批处理 | 有完整快照或稳定批次，小时或日级时效可接受 | 扫描和重算范围可能较大 |
| 文件增量 | 文件只追加、到达可追踪，适合 checkpoint 恢复 | 需要管理 schema、迟到与重放 |
| 数据库 CDC | 需要捕获更新和删除，源端具备可靠日志 | 顺序、重复、DDL 与切换复杂 |
| 事件流 | 事件天然连续，业务确实需要低延迟响应 | 常驻计算、状态和运维要求更高 |

## 决策步骤

1. 先确认可接受延迟、峰值量、历史回补和源端影响。
2. 再确认是否需要更新与删除语义，而不只看新增记录。
3. 比较故障恢复、重复消费、schema 变化和可观测性成本。
4. 记录选中方案、被排除方案及触发重新评估的条件。

## 不适用与人工确认

- 无法获得可靠业务键或顺序字段时，不能把文件到达顺序当作 CDC 顺序。
- 上游会覆盖文件时，必须先定义版本或清单协议。
- 所有延迟与吞吐目标都需要基于实际数据量验证，不能沿用通用数字。
