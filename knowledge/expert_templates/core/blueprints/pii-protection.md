---
id: governance.pii_protection
name: PII 保护设计蓝图
summary: 定义个人信息识别、最小化、脱敏、授权和下游发布边界。
version: 1.1.0
kind: blueprint
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
  - pii
  - masking
  - least-privilege
  - retention
extends: null
official_refs:
  - https://docs.databricks.com/aws/en/data-governance/unity-catalog/access-control/
  - https://docs.databricks.com/aws/en/data-governance/unity-catalog/filters-and-masks
---

# PII 保护设计蓝图

## 适用场景

适用于客户、员工或其他自然人相关字段进入湖仓后的分类、加工与共享设计。具体合规要求必须由组织的法务、安全和数据治理负责人确认，模板不能替代合规结论。

## 数据边界

- 在数据契约中标记直接标识符、准标识符、敏感属性、用途和保留期限。
- Bronze 原始值仅向受控工程与治理角色开放；Silver 生成标准化标识或脱敏值。
- Gold 默认不发布直接联系方式，除非存在经过批准的明确用途和最小字段集合。

## 设计决策

1. 能删除的字段不以脱敏替代删除；能聚合的场景不发布明细。
2. 权限、动态视图、行过滤或列掩码按目标 Runtime、计算模式和维护规模选型并验证限制。
3. Token、Hash 与加密用途不同；关联键方案必须评估可逆性、碰撞、密钥托管和删除需求。
4. 测试数据使用明显虚构值，日志、checkpoint 和隔离表同样纳入敏感数据边界。

## 风险与人工确认项

- 确认数据主体请求、法定保留、跨境和备份删除要求。
- 确认哪些角色可以看原值、脱敏值、聚合值以及审计记录。
- 确认下游导出、缓存和 BI 工具不会绕过平台控制。
