---
id: code.dms_cdc_apply_pyspark
name: DMS CDC 应用 PySpark 模式
summary: 对标准化后的 DMS CDC 批次按业务键去重，并幂等应用插入、更新和删除。
version: 1.2.0
kind: code_pattern
category: pyspark
layer: core
profile: null
cloud: aws
prompt_names:
  - databricks_qa
  - pyspark_generation
  - notebook_generation
  - workflow_design
  - self_check
tags:
  - aws-dms
  - cdc
  - merge
  - pyspark
extends: null
official_refs:
  - https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Target.S3.html
  - https://docs.databricks.com/aws/en/delta/merge
---

# DMS CDC 应用 PySpark 模式

假设上一步已把 DMS 操作与提交时间标准化为 `_op` 和 `_commit_ts`；实际字段必须按 endpoint settings 调整。

```python
from delta.tables import DeltaTable
from pyspark.sql import Window, functions as F

business_key = ["customer_id"]
latest = (
    cdc_batch.withColumn(
        "_row_number",
        F.row_number().over(
            Window.partitionBy(*business_key).orderBy(
                F.col("_commit_ts").desc(), F.col("_ingested_at").desc()
            )
        ),
    )
    .where(F.col("_row_number") == 1)
    .drop("_row_number")
)

target = DeltaTable.forName(spark, "main.silver.customers")
condition = "t.customer_id = s.customer_id"

(
    target.alias("t")
    .merge(latest.alias("s"), condition)
    .whenMatchedDelete(condition="s._op = 'D'")
    .whenMatchedUpdateAll(condition="s._op IN ('I', 'U')")
    .whenNotMatchedInsertAll(condition="s._op IN ('I', 'U')")
    .execute()
)
```

人工确认同一键多事件顺序、删除语义、无主键记录和回补并发；输入批次内部存在冲突时不能直接 `MERGE`。
