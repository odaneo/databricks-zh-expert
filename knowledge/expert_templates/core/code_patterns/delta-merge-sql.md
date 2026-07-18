---
id: code.delta_merge_sql
name: Delta MERGE SQL 模式
summary: 在源批次按业务键去重后，对 Delta 目标表执行可重跑的更新与插入。
version: 1.1.0
kind: code_pattern
category: sql
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - sql_generation
  - self_check
tags:
  - delta
  - merge
  - sql
  - upsert
extends: null
official_refs:
  - https://docs.databricks.com/aws/en/delta/merge
  - https://docs.databricks.com/aws/en/sql/language-manual/delta-merge-into
---

# Delta MERGE SQL 模式

源数据必须先保证一个业务键最多匹配目标的一行；字段和时间窗口按项目契约替换。

```sql
MERGE INTO main.silver.customers AS target
USING (
  SELECT customer_id, customer_name, customer_status, source_updated_at
  FROM (
    SELECT
      *,
      ROW_NUMBER() OVER (
        PARTITION BY customer_id
        ORDER BY source_updated_at DESC, ingested_at DESC
      ) AS row_number
    FROM main.bronze.customer_changes
    WHERE business_date >= :reprocess_from_date
  )
  WHERE row_number = 1
) AS source
ON target.customer_id = source.customer_id
WHEN MATCHED AND source.source_updated_at >= target.source_updated_at THEN
  UPDATE SET
    customer_name = source.customer_name,
    customer_status = source.customer_status,
    source_updated_at = source.source_updated_at
WHEN NOT MATCHED THEN
  INSERT (customer_id, customer_name, customer_status, source_updated_at)
  VALUES (source.customer_id, source.customer_name, source.customer_status, source.source_updated_at);
```

人工确认重复匹配、删除语义、空值覆盖和目标扫描范围；参数必须由调用层绑定，不拼接未校验文本。
