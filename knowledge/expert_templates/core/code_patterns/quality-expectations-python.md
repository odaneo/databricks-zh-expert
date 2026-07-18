---
id: code.quality_expectations_python
name: Lakeflow 数据质量 Expectations Python 模式
summary: 使用可命名的 Lakeflow expectations 记录、丢弃或阻断不符合契约的记录。
version: 1.2.0
kind: code_pattern
category: data_quality
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - pyspark_generation
  - notebook_generation
  - workflow_design
  - self_check
tags:
  - lakeflow
  - expectations
  - data-quality
  - python
extends: null
official_refs:
  - https://docs.databricks.com/aws/en/ldp/expectations
  - https://docs.databricks.com/aws/en/ldp/developer/python-ref
---

# Lakeflow 数据质量 Expectations Python 模式

规则名称表达业务含义；阻断、丢弃或仅记录必须由数据产品负责人确认。

```python
from pyspark import pipelines as dp
from pyspark.sql import functions as F


@dp.table(name="silver_orders", comment="通过基础契约校验的订单")
@dp.expect_or_drop("order_id_required", "order_id IS NOT NULL")
@dp.expect_or_drop("amount_non_negative", "order_amount >= 0")
def silver_orders():
    return (
        spark.readStream.table("main.bronze.orders_raw")
        .withColumn("order_date", F.to_date("event_time"))
        .select("order_id", "customer_id", "order_amount", "event_time", "order_date")
    )
```

先用样本统计规则影响，再决定是否丢弃。需要保留问题记录时，设计独立隔离输出，不能只依赖日志计数。
