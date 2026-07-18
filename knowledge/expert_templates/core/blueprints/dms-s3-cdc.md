---
id: ingestion.dms_s3_cdc
name: AWS DMS 到 S3 CDC 摄取蓝图
summary: 设计 AWS DMS full load 与 CDC 文件进入 S3 后的 Bronze 接入和顺序控制。
version: 1.1.0
kind: blueprint
category: ingestion
layer: core
profile: null
cloud: aws
prompt_names:
  - databricks_qa
  - pyspark_generation
  - workflow_design
  - proposal_generation
tags:
  - aws-dms
  - cdc
  - s3
  - parquet
extends: null
official_refs:
  - https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Target.S3.html
  - https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader
---

# AWS DMS 到 S3 CDC 摄取蓝图

## 适用场景

适用于关系数据库通过 AWS DMS 将 full load 与 CDC 文件写入 S3，再由 Databricks 增量接入的场景。本蓝图只约束 Databricks 侧消费契约，不创建或修改 DMS 任务。

## 输入契约

- 固定源库、表、主键、S3 前缀、文件格式和 DMS endpoint settings。
- 明确操作类型、事务或提交时间、源表标识在输出文件中的字段位置。
- 将 full load 完成点与 CDC 起始点记录为可审计的切换条件。

## 设计决策

1. Bronze 按到达顺序保留 DMS 原始字段、文件元数据与摄取时间，不直接覆盖目标业务表。
2. full load 与 CDC 使用可区分的批次标识；切换前验证记录数、主键唯一性和时间边界。
3. Silver 先按业务键与源提交顺序去重，再处理插入、更新和删除；不能只依赖文件名排序。
4. 对无主键表、DDL 变化和大事务建立单独处置规则，必要时暂停发布而不是猜测顺序。

## 风险与人工确认项

- 确认 Parquet 与 CDC 操作标识的实际 DMS 配置，并用样本文件验证。
- 确认时区、精度、LOB、删除记录和 schema change 的处理约定。
- 确认回补期间如何避免与在线 CDC 重复应用。
