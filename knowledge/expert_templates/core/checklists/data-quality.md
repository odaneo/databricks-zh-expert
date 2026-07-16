---
id: checklist.data_quality
name: 数据质量检查清单
summary: 把完整性、唯一性、有效性、一致性和新鲜度转为可执行规则与处置动作。
version: 1.0.0
kind: checklist
category: data_quality
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - data-quality
  - expectations
  - quarantine
  - checklist
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/ldp/expectations
  - https://docs.databricks.com/aws/en/data-engineering/observability-best-practices
---

# 数据质量检查清单

## 适用场景

用于表设计、Pipeline 发布和数据产品验收，确保规则不仅有 SQL 条件，也有 owner、阈值和处置方式。

## 检查项

- [ ] 表粒度与业务键已明确，重复判断使用业务语义而非整行去重。
- [ ] 必填、范围、枚举、引用完整性和跨字段规则都有可读名称。
- [ ] 新鲜度使用业务事件时间和摄取时间分别监控。
- [ ] 每条规则被标记为仅记录、隔离、丢弃或阻断，并说明原因。
- [ ] 阈值来自历史分布或业务容忍度，不复制通用百分比。
- [ ] 问题记录保留来源、规则、发现时间和修复状态，且权限不弱于主表。
- [ ] 迟到、重放和回填不会被误报为正常增量质量下降。
- [ ] 发布前对账记录数、金额或其他核心指标，并保存差异结论。

## 人工确认项

业务 owner 确认规则含义和容忍度；工程 owner 确认可观测性与隔离流程；治理角色确认敏感问题记录的访问边界。
