---
id: checklist.ingestion_and_schema
name: 摄取与 Schema 演进检查清单
summary: 在发布文件、CDC 或流式摄取前核对输入契约、恢复点和 schema 变化边界。
version: 1.0.0
kind: checklist
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
  - ingestion
  - schema
  - checkpoint
  - checklist
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/data-engineering/schema-evolution
  - https://docs.databricks.com/aws/en/structured-streaming/checkpoints
---

# 摄取与 Schema 演进检查清单

## 适用场景

用于新数据源上线、格式调整、历史回补或 checkpoint 变更前的技术评审。

## 检查项

- [ ] 数据 owner、源路径或 stream、文件格式、业务键和到达频率已记录。
- [ ] full load、增量、更新、删除和迟到数据的表达方式已用样本验证。
- [ ] schema 字段、类型、可空性、时区、精度和兼容策略有版本记录。
- [ ] 未知字段、类型冲突、损坏记录和 rescued data 有明确隔离去向。
- [ ] 每个独立流拥有独立 checkpoint；位置、权限和保留责任已确认。
- [ ] Bronze 保存来源、摄取时间和必要原始载荷，可定位到输入记录。
- [ ] 重放与回补不会和在线增量重复发布同一业务范围。
- [ ] 监控覆盖输入量、空批次、延迟、schema 变化和解析失败。

## 人工确认项

源系统负责人确认契约，平台负责人确认恢复与权限，数据产品负责人确认异常是否阻断下游发布。
