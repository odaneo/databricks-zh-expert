---
id: checklist.cost
name: Databricks 成本检查清单
summary: 以工作负载归属、使用量、调度、计算和存储维护证据评审成本。
version: 1.0.0
kind: checklist
category: cost
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - cost
  - billing
  - utilization
  - checklist
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/admin/usage/system-tables
  - https://docs.databricks.com/aws/en/admin/system-tables/billing
---

# Databricks 成本检查清单

## 适用场景

用于月度成本复盘、新工作负载评审和异常增长调查。模板不提供价格估算，实际金额必须使用账户合同与计费数据确认。

## 检查项

- [ ] workspace、Job、Pipeline、warehouse、owner、环境和数据产品有可追踪标签。
- [ ] 使用 `system.billing.usage` 等受控数据按工作负载和日期归集使用量。
- [ ] 空闲、排队、失败重试、重复调度和无数据运行分别量化。
- [ ] 交互计算、Job compute、SQL warehouse 与管道计算按使用模式选型。
- [ ] 自动停止、最大并发、超时和扩缩容边界已配置并验证。
- [ ] 增量处理避免重复全量扫描，回填限制时间和对象范围。
- [ ] `OPTIMIZE`、保留、checkpoint 和中间表有 owner、频率与删除策略。
- [ ] 成本下降没有以延迟、稳定性、数据质量或恢复能力不可接受地退化为代价。

## 人工确认项

财务或平台 owner 确认计价与预算口径；工程 owner 确认每项优化的服务目标影响和回退方案。
