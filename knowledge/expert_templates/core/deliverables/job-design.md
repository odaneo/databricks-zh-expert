---
id: deliverable.job_design
name: Lakeflow Job 设计书结构
summary: 提供 Job 触发、任务 DAG、参数、计算、重试、监控和恢复的交付骨架。
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
  - lakeflow-jobs
  - job-design
  - runbook
  - delivery
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/jobs
  - https://docs.databricks.com/aws/en/jobs/notifications
---

# Lakeflow Job 设计书结构

## 适用场景

用于新 Job、重大 DAG 调整或生产交接，保证调度图和故障恢复信息可以由非作者复核。

## 交付结构

1. Job 概览：名称、owner、业务目的、环境、服务目标和支持时段。
2. 触发：调度或事件条件、时区、上游到达、并发和补数入口。
3. Task 清单：task key、类型、输入、输出、依赖、参数、计算和完成条件。
4. 依赖图：成功路径、失败路径、条件分支和不可并行的发布步骤。
5. 错误策略：超时、可重试错误、最大重试、最终失败和取消规则。
6. 可观测性：运行状态、时长、数据延迟、质量、通知和日志定位。
7. 恢复：单任务重跑、整链重跑、回填、回滚、幂等和权限。
8. 变更与验收：测试证据、发布顺序、确认人、已知风险和回退条件。

## 人工确认项

每个 task 的运行身份和输出 owner 必须明确；固定等待时间不能代替真实数据依赖或上游完成信号。
