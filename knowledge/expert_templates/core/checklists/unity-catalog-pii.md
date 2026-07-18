---
id: checklist.unity_catalog_pii
name: Unity Catalog 与 PII 检查清单
summary: 在数据发布前核对对象所有权、最小权限、敏感字段和下游暴露范围。
version: 1.1.0
kind: checklist
category: governance
layer: core
profile: null
cloud: neutral
prompt_names:
  - databricks_qa
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - unity-catalog
  - pii
  - privileges
  - checklist
extends: null
official_refs:
  - https://docs.databricks.com/aws/en/data-governance/unity-catalog/manage-privileges/
  - https://docs.databricks.com/aws/en/data-governance/unity-catalog/filters-and-masks
---

# Unity Catalog 与 PII 检查清单

## 适用场景

用于 Catalog、Schema、表或视图发布，以及包含个人信息的数据产品权限评审。

## 检查项

- [ ] Catalog 与 Schema 的环境、业务域和数据层含义没有冲突。
- [ ] 对象 owner 是受控 group 或 service principal，并有交接流程。
- [ ] 读取、写入、管理、审计和生产运行主体职责分离。
- [ ] 权限从实际 consumer group 出发逐项授予，没有借用 owner 权限。
- [ ] 直接标识符、准标识符、敏感属性、用途和保留期限已登记。
- [ ] Gold 与共享视图只暴露消费所需字段，默认不含直接联系方式。
- [ ] 掩码、过滤或动态视图已在目标计算模式下验证行为和限制。
- [ ] 隔离表、日志、checkpoint、导出和缓存采用同等敏感等级控制。
- [ ] 紧急访问、定期复核、离职回收和授权变更留有审计记录。

## 人工确认项

治理、安全与法务确认分类和用途；平台管理员确认 Unity Catalog 与云端 IAM 的组合权限；数据 owner 确认最终消费名单。
