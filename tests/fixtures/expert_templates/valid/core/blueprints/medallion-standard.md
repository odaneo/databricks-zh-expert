---
id: medallion.standard
name: 通用 Medallion 分层设计
summary: 定义 Bronze、Silver、Gold 的职责、输入输出和质量边界。
version: 1.0.0
kind: blueprint
category: medallion
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - sql_generation
  - pyspark_generation
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - bronze
  - silver
  - gold
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/lakehouse/medallion
---

# 通用 Medallion 分层设计

## 适用场景

用于设计可复用的数据分层边界。

## 实施步骤

1. 明确每一层的输入、输出和质量责任。
