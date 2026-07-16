---
id: checklist.performance
name: Databricks 性能检查清单
summary: 从扫描、数据布局、Shuffle、倾斜、并发和计算配置定位性能问题。
version: 1.0.0
kind: checklist
category: performance
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - sql_generation
  - pyspark_generation
  - workflow_design
  - self_check
tags:
  - performance
  - optimize
  - shuffle
  - query-profile
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/optimizations/
  - https://docs.databricks.com/aws/en/delta/optimize
---

# Databricks 性能检查清单

## 适用场景

用于慢 SQL、长时间 Spark Task、Pipeline 延迟上升或资源扩容前的证据化排查。

## 检查项

- [ ] 保存基线运行的输入量、耗时、计算配置和执行计划，避免只比较体感。
- [ ] 过滤条件可下推，避免无必要的 `SELECT *`、重复扫描和过早展开宽表。
- [ ] 表统计、文件数量、文件大小和数据跳过效果与主要查询模式匹配。
- [ ] 分区或聚簇键来自高频过滤条件，且基数与数据增长合理。
- [ ] Shuffle 读写、spill、倾斜 task 和 join 策略已从运行指标确认。
- [ ] 小表广播、缓存和 repartition 只在测量后使用，并记录失效条件。
- [ ] `OPTIMIZE` 的范围与频率按新增数据和查询收益决定，不做无差别全表重写。
- [ ] 并发、启动时间、扩缩容和 SQL warehouse 或 Job compute 类型符合工作负载。

## 人工确认项

先定位瓶颈属于数据布局、查询逻辑、资源不足还是并发等待，再选择单一改动做对照测试并保存结果。
