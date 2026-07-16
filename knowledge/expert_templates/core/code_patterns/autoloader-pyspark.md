---
id: code.autoloader_pyspark
name: Auto Loader PySpark 模式
summary: 提供 S3 文件增量读取、schema 元数据和 checkpoint 分离的最小 PySpark 草稿。
version: 1.0.0
kind: code_pattern
category: pyspark
layer: core
profile: null
cloud: aws
prompt_names:
  - databricks_qa
  - pyspark_generation
  - workflow_design
  - self_check
tags:
  - auto-loader
  - pyspark
  - checkpoint
  - bronze
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader
  - https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/schema
---

# Auto Loader PySpark 模式

将路径、格式、目标表和 schema 策略改为项目配置；每个源使用独立 checkpoint。

```python
source_path = "s3://data-bucket/inbound/orders/"
schema_path = "s3://data-bucket/checkpoints/orders/schema/"
checkpoint_path = "s3://data-bucket/checkpoints/orders/stream/"
target_table = "main.bronze.orders_raw"

source = (
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "json")
    .option("cloudFiles.schemaLocation", schema_path)
    .option("cloudFiles.schemaEvolutionMode", "rescue")
    .load(source_path)
    .selectExpr(
        "*",
        "_metadata.file_path AS _source_file",
        "_metadata.file_modification_time AS _source_modified_at",
        "current_timestamp() AS _ingested_at",
    )
)

(
    source.writeStream.option("checkpointLocation", checkpoint_path)
    .trigger(availableNow=True)
    .toTable(target_table)
)
```

人工确认输入 schema、rescued data 处置、重放范围和目标表权限；不要复用其他流的 checkpoint。
