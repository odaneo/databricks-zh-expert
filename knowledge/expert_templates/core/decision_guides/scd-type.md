---
id: decision.scd_type
name: SCD 类型选择指南
summary: 根据历史追溯、纠错和消费需求选择 SCD Type 1、Type 2 或事件事实表。
version: 1.1.0
kind: decision_guide
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
tags:
  - scd
  - dimensions
  - history
  - cdc
extends: null
official_refs:
  - https://docs.databricks.com/aws/en/ldp/cdc
  - https://docs.databricks.com/aws/en/delta/merge
---

# SCD 类型选择指南

## 适用场景

用于主数据、维度和 CDC 设计时判断是否保留属性历史。SCD 是消费语义，不应仅因为工具支持 Type 2 就默认保留所有字段的每次变化。

## 选择条件

- Type 1：只需要当前有效值，历史错误可被覆盖，消费者不做“当时状态”分析。
- Type 2：需要按生效区间还原历史属性，且业务键、排序字段和迟到规则清晰。
- 事件事实表：每次变化本身就是业务事件，优先保留不可变事件，再派生当前快照或维度。

## 决策步骤

1. 逐字段标注是否需要历史，不要整表一刀切。
2. 明确业务键、变更序列、生效时间、结束时间和当前记录标识。
3. 定义重复事件、乱序、删除、同一时刻多次变更和迟到修正规则。
4. 选择 `MERGE` 或声明式 CDC 前，先用冲突样本验证结果和重跑幂等性。

## 不适用与人工确认

- 缺少稳定业务键或排序字段时，Type 2 结果不可可靠重建。
- 技术摄取时间不能自动等同业务生效时间。
- 下游只要当前状态时，Type 2 的存储与查询复杂度可能没有收益。
