---
id: code.kinesis_pyspark
name: Kinesis Structured Streaming PySpark 模式
summary: 读取 Kinesis 原始记录、解析事件 envelope 并带来源元数据写入 Bronze。
version: 1.1.0
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
  - kinesis
  - structured-streaming
  - pyspark
  - events
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/connect/streaming/kinesis
  - https://docs.databricks.com/aws/en/structured-streaming/checkpoints
---

# Kinesis Structured Streaming PySpark 模式

认证由受控运行身份提供；代码只声明 stream、region、事件 schema 和 checkpoint。

```python
from pyspark.sql import functions as F, types as T

event_schema = T.StructType(
    [
        T.StructField("event_id", T.StringType(), False),
        T.StructField("event_type", T.StringType(), False),
        T.StructField("event_time", T.TimestampType(), False),
        T.StructField("payload", T.StringType(), True),
    ]
)

raw = (
    spark.readStream.format("kinesis")
    .option("streamName", "orders-events")
    .option("region", "ap-northeast-1")
    .option("initialPosition", "latest")
    .load()
)

bronze = raw.select(
    F.from_json(F.col("data").cast("string"), event_schema).alias("event"),
    "partitionKey",
    "sequenceNumber",
    "approximateArrivalTimestamp",
).select("event.*", "partitionKey", "sequenceNumber", "approximateArrivalTimestamp")

(
    bronze.writeStream.option(
        "checkpointLocation", "s3://data-bucket/checkpoints/kinesis/orders/"
    ).toTable("main.bronze.order_events")
)
```

人工确认初始位置、坏事件隔离、event id 去重、水位线和 stream 重建后的 checkpoint 切换。
