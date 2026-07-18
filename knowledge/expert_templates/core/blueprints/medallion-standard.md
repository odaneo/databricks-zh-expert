---
id: medallion.standard
name: 通用 Medallion 分层设计
summary: 定义 Bronze、Silver、Gold 的职责、输入输出、质量门槛和发布边界。
version: 1.1.0
kind: blueprint
category: medallion
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - ddl_generation
  - mapping_generation
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - bronze
  - silver
  - gold
  - delta
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/lakehouse/medallion
  - https://docs.databricks.com/aws/en/lakehouse
---

# 通用 Medallion 分层设计

## 适用场景

适用于需要把原始接入、业务标准化和消费数据产品分离的数据平台。分层是职责边界，不要求每个源机械地复制三张表；低复杂度场景可以合并物理步骤，但必须保留质量与所有权边界。

## 分层职责

- Bronze：保留可追溯的源数据、摄取元数据和失败载荷，支持重放，不承诺业务口径正确。
- Silver：统一类型、主键、去重、时间语义和业务规则，隔离无法修复的记录。
- Gold：围绕明确消费者和指标口径发布稳定数据产品，不暴露不必要的源系统细节。

## 设计决策

1. 每个表写明粒度、业务键、更新方式、迟到规则、质量门槛和责任人。
2. 层间转换保持幂等；回补必须能限定数据范围并验证对下游的影响。
3. schema 与权限从消费契约倒推，不能把 Bronze 的宽松访问直接传播到 Gold。
4. Gold 指标必须附口径、时区、币种、有效期和可接受延迟。

## 风险与人工确认项

- 确认源数据保留期、删除要求和历史重算窗口。
- 确认哪些异常阻断发布，哪些进入隔离表后允许继续。
- 确认每层的服务目标和数据产品负责人。
