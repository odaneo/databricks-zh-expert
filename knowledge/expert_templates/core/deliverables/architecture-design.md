---
id: deliverable.architecture_design
name: Databricks 架构设计书结构
summary: 提供从业务目标到数据流、组件职责、治理和非功能要求的架构交付骨架。
version: 1.0.0
kind: deliverable
category: delivery
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - architecture
  - design-document
  - delivery
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/lakehouse-architecture/reference
  - https://docs.databricks.com/aws/en/lakehouse/medallion
---

# Databricks 架构设计书结构

## 适用场景

用于新数据平台、数据域或重大重构的架构草案。文档必须区分已确认事实、设计建议和待确认假设。

## 交付结构

1. 背景与目标：业务问题、消费者、成功指标、范围和非目标。
2. 现状与约束：源系统、数据量、时效、合规、网络和组织边界。
3. 逻辑数据流：来源、摄取、Bronze、Silver、Gold、消费和反馈路径。
4. 组件职责：每个 Pipeline、Job、表、接口和外部服务的 owner 与边界。
5. 数据设计：粒度、业务键、schema、更新、质量、回填和保留。
6. 治理与安全：Unity Catalog、运行身份、敏感字段、最小权限和审计。
7. 非功能设计：服务目标、扩展、恢复、监控、成本归属和容量假设。
8. 实施与迁移：里程碑、依赖、验收、切换、回滚和未决事项。

## 人工确认项

附决策记录表，至少包含议题、方案、选择理由、影响、确认人和日期；不把尚未验证的容量或性能写成结论。
