---
id: deliverable.table_design
name: Delta 表定义书结构
summary: 提供表级业务语义、字段、键、更新、质量、权限和运维信息的交付骨架。
version: 1.2.0
kind: deliverable
category: delivery
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - ddl_generation
  - mapping_generation
  - sql_generation
  - pyspark_generation
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - table-design
  - delta
  - schema
  - delivery
extends: null
official_refs:
  - https://docs.databricks.com/aws/en/delta/
  - https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-datatypes
---

# Delta 表定义书结构

## 适用场景

用于 Bronze、Silver、Gold 或运维表的设计评审与交接，重点是业务契约，而不只是字段 DDL。

## 交付结构

| 区域 | 必填内容 |
| --- | --- |
| 表概览 | 完整名称、层、用途、owner、消费者、数据分类 |
| 粒度与键 | 一行含义、业务键、技术键、重复定义 |
| 字段 | 名称、类型、可空、业务含义、来源、转换、敏感级别 |
| 更新 | 全量或增量、插入更新删除、迟到、重放、回填、幂等规则 |
| 质量 | 完整性、唯一性、有效性、对账和阻断条件 |
| 物理设计 | 数据量、增长、布局依据、维护动作和保留 |
| 治理 | owner、读取组、写入身份、掩码或过滤、审计要求 |
| 运维 | SLA、监控、告警、恢复、依赖和已知限制 |

## 人工确认项

字段示例必须为虚构值；业务 owner 确认口径，工程 owner 确认更新与恢复，治理 owner 确认分类和权限。
