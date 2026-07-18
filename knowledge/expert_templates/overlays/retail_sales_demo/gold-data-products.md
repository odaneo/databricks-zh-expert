---
id: retail.gold_data_products
name: 零售 Gold 数据产品定义
summary: 定义每日销售、商品表现、库存健康、客户与渠道四个 Gold 产品的粒度和质量契约。
version: 1.1.0
kind: deliverable
category: medallion
layer: retail_sales_demo
profile: retail_sales_demo
cloud: aws
prompt_names:
  - databricks_qa
  - sql_generation
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - retail
  - gold
  - data-product
  - metrics
extends: medallion.standard
official_refs:
  - https://docs.databricks.com/aws/en/lakehouse/medallion
  - https://docs.databricks.com/aws/en/data-governance/unity-catalog/
---

# 零售 Gold 数据产品定义

## 适用场景

本资产为 `retail_sales_demo` 项目提供 Gold 交付契约，扩展通用 Medallion 边界。指标、维度和刷新目标必须由业务 owner 确认后才能成为正式口径。

## 数据产品交付定义

| 数据产品 | 建议表与粒度 | 核心字段或指标 | 预期消费者 |
| --- | --- | --- | --- |
| 每日销售分析 | `gold.daily_sales`，日期 × 门店 × 渠道 × 商品 | 净销售额、订单量、销售件数、客单价、退款额 | `analyst`、`finance` |
| 商品表现分析 | `gold.product_performance`，日期 × 商品 × 渠道 | 销量、退货率、折扣影响、品类排名 | `analyst`、`marketing` |
| 库存健康分析 | `gold.inventory_health`，时点 × 门店 × 商品 | 可售库存、缺货标识、覆盖天数、库存周转 | `analyst`、`data_engineer` |
| 客户与渠道分析 | `gold.customer_channel`，日期 × 分群 × 渠道 | 新老客户数、转化率、渠道贡献、复购指标 | `analyst`、`marketing` |

## 发布与质量决策

1. 日批产品在 07:00 前完成更新，并在对账和质量检查通过后于 07:30 前标记为可查询。
2. 近实时渠道指标以 Kinesis 事件为输入，目标延迟为 5 分钟；正式报表仍以已对账批次为准。
3. 每张表公布粒度、owner、刷新时间、口径版本、上游依赖、质量状态和回填范围。
4. 销售与支付金额、订单和销售行数量、库存快照日期必须可与 Silver 或源控制总数对账。
5. Gold 不暴露原始姓名、邮箱、手机号或地址，只允许分析标识和非直接识别属性。

## 人工确认项

- 确认退款、取消、税费、运费、折扣和币种对净销售额的影响。
- 确认库存周转周期、缺货阈值、客户新老定义和转化漏斗窗口。
- 确认迟到数据触发重算的日期范围，以及发布后指标修订的通知方式。
