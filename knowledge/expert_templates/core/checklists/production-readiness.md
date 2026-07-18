---
id: checklist.production_readiness
name: 生产就绪检查清单
summary: 在 Databricks 数据产品上线前统一检查契约、恢复、治理、监控和交付责任。
version: 1.1.0
kind: checklist
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
  - production
  - readiness
  - acceptance
  - checklist
extends: null
official_refs:
  - https://docs.databricks.com/aws/en/data-engineering/observability-best-practices
  - https://docs.databricks.com/aws/en/jobs
---

# 生产就绪检查清单

## 适用场景

用于 Pipeline、Job、表和数据产品首次上线或重大变更发布前的统一验收。

## 检查项

- [ ] 需求、范围、数据源、表粒度、业务键、口径和非目标均已签字确认。
- [ ] dev、test、prod 的对象命名、运行身份、参数和权限互相隔离。
- [ ] 代码、配置、schema 和依赖均有版本，可从受控来源重新部署。
- [ ] 正常增量、空输入、重复、迟到、schema 变化和失败恢复已测试。
- [ ] 回填、重放、单任务重跑、回滚和紧急停止有经过演练的 runbook。
- [ ] 数据质量、运行状态、数据延迟和成本监控有 owner 与告警目的地。
- [ ] Unity Catalog 权限、敏感字段、保留和审计要求已复核。
- [ ] 上下游依赖、服务目标、支持时段和故障沟通方式已登记。
- [ ] 发布证据包含测试结果、对账、已知风险、人工确认和回退条件。

## 人工确认项

业务、数据工程、平台、治理和运维角色分别确认自身责任；任何未关闭项必须记录接受人、期限和影响。
