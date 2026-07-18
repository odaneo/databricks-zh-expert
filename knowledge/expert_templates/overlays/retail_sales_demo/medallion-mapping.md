---
id: retail.medallion_mapping
name: 零售 Medallion 模拟映射
summary: 将零售日批、CDC 和事件数据映射到 Bronze、Silver、Gold 表及质量边界。
version: 1.1.0
kind: blueprint
category: medallion
layer: retail_sales_demo
profile: retail_sales_demo
cloud: aws
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
  - retail
  - medallion
  - delta
  - pii
extends: medallion.standard
is_mock: true
official_refs:
  - https://docs.databricks.com/aws/en/lakehouse/medallion
  - https://docs.databricks.com/aws/en/ldp/concepts
---

# 零售 Medallion 模拟映射

## 适用场景

本资产为 `retail_sales_demo` 模拟项目补充表级分层约定，扩展通用 Medallion 设计。表名、业务键和质量阈值是设计起点，不是已上线的数据契约。

## 分层设计决策

| 层 | 模拟表 | 处理职责 | 关键质量边界 |
| --- | --- | --- | --- |
| Bronze | `pos_sales_raw`、`supplier_product_raw` | 保留 S3 Parquet 原始字段、文件名和摄取时间 | 可追溯文件、重复文件可识别、解析失败可隔离 |
| Bronze | `customer_cdc_raw`、`product_cdc_raw`、`store_cdc_raw`、`inventory_cdc_raw` | 保留 AWS DMS full load + CDC 操作、提交时间和主键 | 删除事件不丢失、CDC 顺序可恢复、15 分钟延迟可测量 |
| Bronze | `order_event_raw`、`payment_event_raw`、`customer_behavior_raw` | 保留 Kinesis 原始事件和流元数据 | `event_id` 可追踪、坏记录隔离、5 分钟延迟可观测 |
| Silver | `sales_line`、`dim_product`、`dim_store`、`inventory_snapshot` | 类型统一、去重、业务键校验、迟到处理和主数据关联 | 主键唯一、金额非负、引用完整、事件时间合理 |
| Silver | `customer_secure`、`order_enriched`、`payment_status`、`behavior_session` | 客户受控关联、订单支付匹配、行为会话化 | PII 脱敏、订单金额对账、支付状态合法 |
| Gold | `daily_sales`、`product_performance`、`inventory_health`、`customer_channel` | 发布四个零售数据产品 | 口径稳定、批次完整、刷新时间和可见权限达标 |

## PII 处理边界

Bronze 原始客户数据可以保留虚构姓名、邮箱、手机号和地址，但只能由受限 `data_engineer` 运行身份访问。Silver 对联系方式进行标准化和脱敏，只保留受控关联标识。Gold 不暴露原始姓名、邮箱、手机号或地址，仅提供分析标识、会员等级和不直接识别个人的分群属性。

## 人工检查项

- [ ] 确认销售行、订单、支付、库存和客户维度的业务键及粒度。
- [ ] 确认 CDC 删除、迟到事件、退款、取消和跨日更正对各层的影响。
- [ ] 确认四个 Gold 产品的指标口径、刷新方式、owner 和历史重算边界。
- [ ] 确认 Bronze 保留期、Silver 脱敏方式和 Gold 发布审批符合治理要求。
