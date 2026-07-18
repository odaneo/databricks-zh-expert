---
id: checklist.workflow_monitoring
name: 工作流监控检查清单
summary: 核对 Lakeflow Jobs 与 Pipelines 的状态、延迟、重试、通知和恢复入口。
version: 1.1.0
kind: checklist
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
  - jobs
  - monitoring
  - alerts
  - runbook
extends: null
official_refs:
  - https://docs.databricks.com/aws/en/jobs
  - https://docs.databricks.com/aws/en/jobs/notifications
  - https://docs.databricks.com/aws/en/data-engineering/observability-best-practices
---

# 工作流监控检查清单

## 适用场景

用于新 Job 上线、调度调整、告警治理和故障复盘，覆盖从触发到下游发布的完整链路。

## 检查项

- [ ] Job、Task、Pipeline 和数据产品均有 owner 与可联系的支持组。
- [ ] 监控成功率、运行时长、排队时间、数据延迟、输入量和质量结果。
- [ ] 超时与重试只覆盖可恢复故障，并设置最大次数和总时长。
- [ ] 通知区分最终失败、持续时间超限、未触发、无数据和恢复事件。
- [ ] 告警包含 run id、失败 task、业务日期、影响对象和 runbook 链接。
- [ ] 单任务重跑、整链重跑、取消和回滚的权限及幂等性已验证。
- [ ] 并发运行、补数运行和正常调度不会覆盖同一发布范围。
- [ ] 运行历史与事件日志的保留时间满足复盘和审计要求。

## 人工确认项

业务负责人确认告警服务目标和影响等级；工程负责人确认恢复步骤；平台负责人确认通知目的地与运行身份权限。
