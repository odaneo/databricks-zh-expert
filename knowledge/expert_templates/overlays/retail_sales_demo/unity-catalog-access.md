---
id: retail.unity_catalog_access
name: 零售 Unity Catalog 模拟权限矩阵
summary: 固定零售开发、测试、生产环境以及五类角色的最小权限和 PII 边界。
version: 1.0.0
kind: blueprint
category: governance
layer: retail_sales_demo
profile: retail_sales_demo
cloud: aws
prompt_names:
  - databricks_qa
  - workflow_design
  - proposal_generation
  - self_check
tags:
  - retail
  - unity-catalog
  - access-control
  - pii
extends: governance.unity_catalog
is_mock: true
official_refs:
  - https://docs.databricks.com/aws/en/data-governance/unity-catalog/access-control/
  - https://docs.databricks.com/aws/en/data-governance/unity-catalog/filters-and-masks
---

# 零售 Unity Catalog 模拟权限矩阵

## 适用场景

本资产为 `retail_sales_demo` 模拟项目提供 Unity Catalog 权限草案，扩展通用治理蓝图。角色名表示职责，不对应任何实际用户、组或已创建的授权。

## 环境与对象边界

- Catalog 固定为 `retail_dev`、`retail_test`、`retail_prod`，分别使用独立运行身份和存储凭据。
- 每个 Catalog 包含 `bronze`、`silver`、`gold`、`ops`；跨环境读取默认禁止，发布数据通过受控流程迁移。
- 所有者负责管理对象生命周期，不把日常查询组设为 Catalog 或 Schema owner。

## 角色权限决策

| 角色 | Bronze | Silver | Gold | ops |
| --- | --- | --- | --- | --- |
| `data_engineer` | 通过管道身份读写，受限读取原始客户数据 | 读写转换表 | 发布与维护 | 读写运行记录 |
| `analyst` | 无 | 只读非敏感主题 | 只读四个数据产品 | 只读公开质量摘要 |
| `marketing` | 无 | 只读受控客户分群视图 | 只读客户与渠道分析 | 无 |
| `finance` | 无 | 只读销售与支付对账视图 | 只读每日销售和商品表现 | 只读发布状态 |
| `auditor` | 不读取业务行，按审批查看审计证据 | 元数据与授权审计 | 元数据与口径审计 | 只读审计日志 |

## PII 与检查项

Bronze 原始客户数据仅允许受限 `data_engineer` 路径访问。Silver 对联系方式进行标准化和脱敏，并以受控键关联。Gold 不暴露原始姓名、邮箱、手机号或地址；`marketing` 只能使用分析标识、会员等级和非直接识别分群。

- [ ] 通过组授权，不向个人直接授予长期生产权限。
- [ ] Pipeline 和 Job 使用服务主体，人与工作负载身份分离。
- [ ] 权限提升、紧急访问、离职回收和定期复核均有 owner 与审计证据。
- [ ] 行过滤或列掩码的适用范围、性能影响和测试证据在上线前确认。
