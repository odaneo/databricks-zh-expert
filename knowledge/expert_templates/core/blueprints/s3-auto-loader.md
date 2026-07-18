---
id: ingestion.s3_auto_loader
name: S3 Auto Loader 增量摄取蓝图
summary: 设计从 Amazon S3 持续发现文件并写入 Bronze Delta 表的增量摄取边界。
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
  - s3
  - auto-loader
  - bronze
  - schema-evolution
extends: null
official_refs:
  - https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader
  - https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/schema
---

# S3 Auto Loader 增量摄取蓝图

## 适用场景

适用于文件持续到达 Amazon S3、需要可恢复地增量发现文件并落入 Bronze Delta 表的工作负载。一次性小文件导入或已有上游严格批次清单时，应先比较普通批读取的复杂度。

## 输入与前置条件

- 明确源路径、文件格式、到达频率、迟到窗口和历史回补范围。
- 为每个独立数据源分配独立的 schema location 与 checkpoint location。
- 目标表、外部位置和运行身份必须纳入 Unity Catalog 权限设计。

## 设计决策

1. Bronze 保留源字段，并补充源文件路径、修改时间、摄取时间和批次标识。
2. 已知契约稳定时显式提供 schema；允许新增字段时，选择可审计的演进模式并监控 rescued data。
3. 连续流与 `AvailableNow` 二选一，由数据新鲜度和调度边界决定，不在同一 checkpoint 上来回切换语义。
4. 将解析失败与业务质量失败分开：前者保留原始载荷，后者交给 Silver 规则处理。

## 风险与人工确认项

- 确认上游是否会覆盖同名文件、改变分区目录或重放历史文件。
- 确认 schema 变化后的发布、重启和告警流程。
- 确认 checkpoint 与 schema 元数据的保留、备份和权限责任人。
