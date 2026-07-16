---
id: governance.unity_catalog
name: Unity Catalog 治理蓝图
summary: 设计 Catalog、Schema、对象所有权、最小权限和环境隔离边界。
version: 1.0.0
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
  - unity-catalog
  - privileges
  - ownership
  - governance
extends: null
is_mock: false
official_refs:
  - https://docs.databricks.com/aws/en/data-governance/unity-catalog/
  - https://docs.databricks.com/aws/en/data-governance/unity-catalog/manage-privileges/
  - https://docs.databricks.com/aws/en/data-governance/unity-catalog/access-control/
---

# Unity Catalog 治理蓝图

## 适用场景

适用于需要在 Databricks 中统一管理数据对象、权限、所有权和环境边界的项目。蓝图只给出设计草案，实际授权必须由具备相应职责的管理员审核执行。

## 对象与所有权

- Catalog 表达环境、业务域或隔离边界，Schema 表达数据层或子域，避免同时承担过多含义。
- 所有权优先授予受控 group 或 service principal，不依赖单个员工账号。
- 外部位置、存储凭据和 workspace binding 与数据对象权限分别评审。

## 设计决策

1. 从 consumer group 到所需对象逐层授予最小权限，不用对象 owner 作为日常读取身份。
2. 数据工程写入、分析读取、治理管理和审计查看分离，生产发布身份不可交互共享。
3. 为 Catalog、Schema、Table、View、Volume 和 Function 建立权限矩阵与变更审批记录。
4. 定期核对显式授权、继承授权、对象 owner 和长期不用的主体。

## 风险与人工确认项

- 确认环境是分 Catalog、分 workspace，还是两者共同隔离。
- 确认外部位置与云端 IAM 的责任边界，避免只检查 Unity Catalog。
- 确认紧急访问、离职回收和审计证据的保留流程。
