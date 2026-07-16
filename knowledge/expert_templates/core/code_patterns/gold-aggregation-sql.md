---
id: code.gold_aggregation_sql
name: Gold 聚合 SQL 模式
summary: 以明确粒度、口径和维度键生成可审计的每日指标表草稿。
version: 1.0.0
kind: code_pattern
category: sql
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - sql_generation
  - proposal_generation
  - self_check
tags:
  - gold
  - aggregation
  - sql
  - metrics
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-qry-select
  - https://docs.databricks.com/aws/en/lakehouse/medallion
---

# Gold 聚合 SQL 模式

示例粒度为 `sales_date + store_id + channel`；收入、取消和时区口径必须先由业务确认。

```sql
CREATE OR REPLACE TABLE main.gold.daily_sales AS
SELECT
  DATE(CONVERT_TIMEZONE('UTC', :business_timezone, order_timestamp)) AS sales_date,
  store_id,
  channel,
  COUNT(DISTINCT order_id) AS order_count,
  SUM(CASE WHEN order_status = 'COMPLETED' THEN net_amount ELSE 0 END) AS net_sales_amount,
  SUM(CASE WHEN order_status = 'RETURNED' THEN net_amount ELSE 0 END) AS returned_amount,
  MAX(current_timestamp()) AS refreshed_at
FROM main.silver.orders
WHERE order_timestamp >= :reprocess_from_timestamp
  AND order_timestamp < :reprocess_to_timestamp
GROUP BY
  DATE(CONVERT_TIMEZONE('UTC', :business_timezone, order_timestamp)),
  store_id,
  channel;
```

生产实现应选择增量发布或受控范围覆盖，并对总额、订单数、重复键和迟到订单进行发布前对账。
