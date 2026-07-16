---
id: retail.production_acceptance
name: AWS 零售平台模拟生产验收清单
summary: 按零售数据源、SLA、恢复、质量、治理和交付责任检查生产就绪状态。
version: 1.0.0
kind: checklist
category: delivery
layer: retail_sales_demo
profile: retail_sales_demo
cloud: aws
prompt_names:
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - retail
  - acceptance
  - production-readiness
  - mock
extends: checklist.production_readiness
is_mock: true
official_refs:
  - https://docs.databricks.com/aws/en/data-engineering/observability-best-practices
  - https://docs.databricks.com/aws/en/jobs
---

# AWS 零售平台模拟生产验收清单

## 适用场景

本资产用于 `retail_sales_demo` 模拟项目上线评审，扩展通用生产就绪清单。勾选项只表示需要收集的证据，不能预填为通过，也不能据此声称 AWS 或 Databricks 资源已经运行。

## 验收检查项

### 数据源与恢复

- [ ] S3 POS 和供应商文件的迟到、空批次、重复、补档与 schema 变化已经测试。
- [ ] AWS DMS full load + CDC 到 S3 Parquet 的主键、删除、乱序、中断恢复和 15 分钟延迟已经验证。
- [ ] Kinesis order、payment、customer_behavior 的重复、迟到、坏记录、重放和 5 分钟延迟已经验证。
- [ ] Auto Loader 与 Structured Streaming 的 checkpoint、schema 位置、权限和恢复 runbook 已复核。

### 数据产品与 SLA

- [ ] 每日销售分析、商品表现分析、库存健康分析、客户与渠道分析均有 owner、粒度和口径版本。
- [ ] POS 05:00 到达、Gold 07:00 更新、07:30 可查询的测量证据和失败升级路径已准备。
- [ ] 核心任务 99.5% 模拟月度成功率的统计窗口、排除项和维护窗口已确认。
- [ ] 销售、支付、库存与客户指标具有源到 Gold 的对账证据，失败时阻止发布。

### 治理与交付

- [ ] `retail_dev`、`retail_test`、`retail_prod` 及其 `bronze`、`silver`、`gold`、`ops` 已完成环境隔离检查。
- [ ] `data_engineer`、`analyst`、`marketing`、`finance`、`auditor` 权限符合最小授权并完成复核。
- [ ] Bronze 原始客户数据受限，Silver 对联系方式进行标准化和脱敏，Gold 不暴露原始姓名、邮箱、手机号或地址。
- [ ] 告警、值班、重跑、回填、回滚、变更审批和事故沟通均有负责人及可访问的操作手册。

## 人工确认项

任何未通过项都必须记录影响、临时措施、接受人和截止日期。模拟 SLA 不能替代项目签字，生产发布必须由业务、数据工程、平台、治理和运维责任人共同确认。
