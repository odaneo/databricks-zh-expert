---
id: retail.workflow_dag
name: AWS 零售工作流 DAG
summary: 定义日批、CDC、Kinesis Pipeline 与 Gold 发布任务的依赖、时限和失败边界。
version: 1.1.0
kind: blueprint
category: workflow
layer: retail_sales_demo
profile: retail_sales_demo
cloud: aws
prompt_names:
  - databricks_qa
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - retail
  - workflow
  - lakeflow-jobs
  - sla
extends: workflow.lakeflow_jobs
official_refs:
  - https://docs.databricks.com/aws/en/jobs
  - https://docs.databricks.com/aws/en/jobs/notifications
---

# AWS 零售工作流 DAG

## 适用场景

本资产为 `retail_sales_demo` 项目定义 Lakeflow Jobs 与 Pipeline 的依赖草案，扩展通用工作流蓝图。调度时间和重试策略需要结合目标 workspace、数据量和支持时段重新确认。

## 工作流依赖

```text
kinesis_continuous_pipeline -------------------------------> realtime_gold_publish

pos_arrival_check -> pos_bronze -> sales_silver -----------+
supplier_arrival_check -> product_bronze -> product_silver +--> daily_gold_refresh -> quality_gate -> publish
dms_cdc_pipeline -> customer/product/store/inventory ------+
```

- `kinesis_continuous_pipeline` 持续处理 order、payment、customer_behavior，监控端到端 5 分钟目标。
- `dms_cdc_pipeline` 持续摄取 S3 Parquet，监控 CDC 进入 Bronze 不超过 15 分钟。
- 日批在每日 05:00 后检查 POS 与供应商文件，07:00 前完成 Gold 更新，07:30 前通过质量门并可查询。
- 每个 Pipeline 使用独立运行身份、checkpoint 和并发策略；失败重跑不得跳过上游完整性检查。

## 编排设计决策

1. 连续 Pipeline 的健康状态作为下游发布条件，不通过定时停止和重启模拟流式处理。
2. 文件未到、空批次、质量阻断和系统失败使用不同结果状态与通知，避免统一按技术重试处理。
3. Gold 发布前执行销售金额对账、主键唯一性、引用完整性、PII 列检查和刷新时间检查。
4. 核心任务的 99.5% 是基线月度成功率目标；统计口径排除项和维护窗口必须由项目确认。

## 监控与人工确认项

- 为到达延迟、处理延迟、隔离记录、任务失败、质量阻断和 Gold 新鲜度设置 owner 与通知目的地。
- 记录单任务重跑、日期回补、Kinesis 重放和 DMS CDC 恢复的 runbook，不把全量刷新作为默认恢复方式。
- 确认业务时区、日界线、节假日批次、最大重试次数、超时和升级路径。
