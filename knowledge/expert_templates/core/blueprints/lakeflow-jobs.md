---
id: workflow.lakeflow_jobs
name: Lakeflow Jobs 工作流蓝图
summary: 设计任务 DAG、参数、重试、调度、通知和人工恢复边界。
version: 1.0.0
kind: blueprint
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
  - lakeflow-jobs
  - dag
  - scheduling
  - monitoring
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/jobs
  - https://docs.databricks.com/aws/en/jobs/notifications
---

# Lakeflow Jobs 工作流蓝图

## 适用场景

适用于需要按依赖关系运行 Notebook、Python、SQL 或 Pipeline 任务，并统一处理调度、参数和告警的工作流。数据集内部依赖优先留在声明式管道，跨管道或非数据处理步骤再由 Job 编排。

## DAG 设计

- 一个任务只承担一个可重试的业务步骤，并声明输入、输出和完成条件。
- 依赖边表达真实数据依赖，不用固定等待时间模拟上游完成。
- 公共运行参数从 Job 入口传入，任务参数只保留本步骤需要的值。

## 设计决策

1. 仅对瞬时故障配置有限重试；数据质量、权限和代码错误应快速失败并保留诊断信息。
2. 为并发、超时、队列和补数运行定义边界，防止同一业务日期重复发布。
3. 通知区分首次失败、最终失败、持续时间超限和恢复，减少重复噪声。
4. 记录任务 owner、runbook、上游 SLA、下游影响和人工重跑入口。

## 风险与人工确认项

- 确认时区、节假日、数据到达与调度时间的关系。
- 确认失败后从单任务重跑还是整条 DAG 重跑，并验证幂等性。
- 确认生产身份、计算策略和通知目的地由谁维护。
