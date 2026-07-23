<!--
文件用途：集中定义 Northwind 销售分析项目的数据分类、敏感字段边界、访问控制、保留与删除、调度、SLA、Owner、监控、告警、重跑、恢复、审计和成本要求。
维护责任：由用户手动维护并确认组织和运行要求。Agent 可以读取、引用、检查一致性并生成实施草稿，不得擅自改变治理决定，也不得声称任何权限、告警、审计、恢复或成本控制已经部署或验证。
事实依据：源表、字段、数据类型、主键、外键和可空性只以 source-schema/northwind-schema.sql 为准。业务口径以已确认业务与数据规则文件为准。架构、摄取、调度、恢复和平台边界以项目需求及项目架构与摄取约束文件为准。数据产品范围以数据产品定义文件为准。质量门禁、隔离和严重等级以数据质量要求文件为准。
优先关系：源结构事实遵循 Northwind SQL 文件。业务口径遵循已确认业务与数据规则。平台与运行约束遵循项目需求和项目架构文件。质量处置遵循数据质量要求。文件之间出现冲突时必须停止受影响设计，提交冲突清单，并由用户完成文档变更和人工确认。
状态边界：本文定义应采用的治理和运维合同，不代表真实 AWS、Databricks、RDS、DMS、S3、Unity Catalog、告警、审计或成本资源已经创建、运行、授权或通过验收。
内容边界：可以记录分类、权限、保留、删除、SLA、Owner、监控、告警、升级、重跑、补数、恢复、审计和成本规则。不得写入 Token、IAM Secret、数据库密码、真实个人联系方式、真实账户编号、真实资源 ARN、真实端点、真实 Workspace 编号或虚构的运行结果。
-->

# 治理与运维要求

## 文档定位

本文是 Northwind 销售分析项目的治理与运维权威输入，回答以下问题：

- 哪些数据可以进入平台
- 哪些字段属于 Restricted、Confidential 或 Internal
- 哪些主体可以访问 Landing、Bronze、Silver、Gold 和 Ops
- 数据保留多久，源端删除和法定删除如何处理
- 作业何时运行，SLA、RPO 和 RTO 如何定义
- 发生失败、积压、质量异常或安全事件时如何告警和升级
- 如何执行重跑、补数、恢复和数据代际切换
- 如何限制 AWS 与 Databricks 成本并保留审计证据

本文适用于 `dev`、`test` 和 `prod` 三个环境。所有 Terraform、Databricks Asset Bundles、Lakeflow Pipeline、Lakeflow Job、SQL Warehouse、Unity Catalog 授权、监控规则、Runbook 和发布流程必须遵守本文。

真实运行状态只能由目标环境的资源清单、Unity Catalog 权限记录、AWS 与 Databricks 审计日志、告警事件、运行记录、质量结果、对账结果、发布水位和账单使用量证明。

## 治理原则

### 事实与设计分离

源系统事实只来自 Northwind SQL 文件。本文中的分类、权限、保留期、SLA、告警阈值、恢复目标、Owner 和预算属于已确认项目决策。

部署运行变量包括 AWS 账户编号、资源 ARN、RDS 端点、Workspace 编号、Metastore 编号、KMS Key 标识和通知目标编号。部署运行变量必须从真实环境读取，不得使用看似真实的占位值。

本文不得被用来证明基础设施已经部署，也不得被用来证明质量检查、权限验收、告警投递、恢复演练或成本控制已经通过。

### 最小数据原则

项目源 Schema 包含 14 张表和 92 个字段。已批准摄取 62 个字段，固定排除 30 个 Restricted 字段。

DMS 必须使用显式表选择和显式字段白名单。未被批准的字段不得进入 DMS 落地区、S3、Landing、Bronze、Silver、Gold 或 Ops。

新增源字段默认不得摄取。任何字段纳入必须先完成业务用途、分类、权限、保留期、质量、产品影响和删除影响评审。

### 最小权限原则

权限优先授予账户级 Group 和专用 Service Principal。生产数据权限不得直接授予个人用户。

每个主体只获得完成职责所需的最小 Catalog、Schema、Table、Volume、Storage Credential、External Location 和运行权限。

开发、测试和生产环境必须隔离。开发和测试主体不得获得生产 Catalog 的 `USE CATALOG`，生产 Catalog 不得绑定开发或测试 Workspace。

### 可追溯原则

所有运行、质量、对账、发布、权限、告警、重跑、补数、恢复和成本决定必须保留可查询证据。

任何人工豁免、紧急访问、超过 90 天的补数、预算调整、保留期变更或数据代际切换都必须记录申请、批准、影响范围、执行身份、执行时间和验证结果。

### 默认拒绝原则

未明确批准的访问、字段、导出、跨环境读取、跨 Catalog 写入、个人直授权和本地 Workspace Group 一律拒绝。

任何 Restricted 字段进入平台都视为安全边界失效，必须停止受影响环境的发布并按 Sev 1 处置。

## 数据分类与敏感字段

### 分类等级

| 分类 | 定义 | 默认处理 |
|---|---|---|
| Restricted | 联系人、电话、详细地址、个人出生信息、员工备注、图片、图片路径和订单收货明细等高敏感数据 | 在 DMS 字段白名单阶段排除，不进入 S3 或 Databricks |
| Confidential | 客户公司名、员工姓名与任职信息、供应商公司名、承运商公司名，以及获准保留的城市、地区和国家等受限业务信息 | 只按批准用途发布，使用最小权限、审计和必要的列级保护 |
| Internal | 订单、订单明细、商品、品类、库存、销售区域、标识符和聚合指标 | 仅供项目内部授权用途，不对公众发布 |
| Public | 当前没有源字段或数据产品属于 Public | 不建立公共发布渠道 |

分类适用于源字段、派生字段、聚合结果、临时数据、隔离数据、导出副本、缓存和日志。派生、汇总或别名处理不会自动降低数据分类。

### Restricted 字段清单

以下 30 个字段固定归类为 Restricted，并在 DMS 字段白名单阶段排除：

| 源表 | Restricted 字段 | 数量 |
|---|---|---:|
| `categories` | `picture` | 1 |
| `customers` | `contact_name`、`contact_title`、`address`、`postal_code`、`phone`、`fax` | 6 |
| `employees` | `title_of_courtesy`、`birth_date`、`address`、`city`、`region`、`postal_code`、`country`、`home_phone`、`extension`、`photo`、`notes`、`photo_path` | 12 |
| `orders` | `ship_name`、`ship_address`、`ship_postal_code` | 3 |
| `shippers` | `phone` | 1 |
| `suppliers` | `contact_name`、`contact_title`、`address`、`postal_code`、`phone`、`fax`、`homepage` | 7 |
| 合计 | 固定排除字段 | 30 |

Restricted 源列不得进入 DMS 落地区或 Databricks 数据对象。Restricted 源值不得进入以下位置：

- DMS S3 落地文件
- Landing External Volume 可见文件内容
- Bronze、Silver、Gold 和 Ops 表
- Pipeline 参数、Notebook 输出和 Job 日志
- 质量结果、隔离错误摘要和告警正文
- BI 查询结果缓存和未经批准的导出副本
- 未批准的 Git 仓库数据样例、工单附件和聊天记录

注册结构事实文件 `source-schema/northwind-schema.sql` 只包含结构 DDL。完整上游脚本 `upstream/northwind.sql` 可以保留原始样例内容，因此属于受控审计与验收资产；它不注册为 Agent 上下文，也不得发送给模型、作为不受限日志输入或作为数据产品来源，其访问和分发必须遵循 Restricted 资产控制。

治理文档、字段白名单和质量证据可以记录 Restricted 字段标识、规则标识和命中数量，不得记录 Restricted 字段值。

Restricted 字段扫描在每次发布前执行。发现任一 Restricted 源列进入 DMS 落地区或 Databricks，或发现 Restricted 源值进入未批准输出时，必须执行以下动作：

1. 停止受影响 Pipeline 和 Gold 发布
2. 将受影响产品状态更新为 `blocked`
3. 创建 Sev 1 事件
4. 同时通知平台 Owner 和安全 Owner
5. 识别受影响的 S3 对象、Delta 表、日志、缓存和导出副本
6. 按安全 Owner 批准的处置方案隔离或删除受影响数据
7. 事件证据表明凭证或访问授权可能受影响时，立即轮换或撤销相关凭证和权限
8. 完成范围确认、根因分析、清理验证和审计证据留存
9. 通过安全验收和数据质量门禁后恢复发布

Restricted 事件不得通过普通数据质量豁免关闭。

### Confidential 字段范围

以下字段和逻辑属性固定归类为 Confidential：

| 对象 | Confidential 内容 |
|---|---|
| 客户 | `company_name`，获准保留的 `city`、`region` 和 `country` |
| 员工 | `first_name`、`last_name`、`title`、`hire_date`、`reports_to`，以及由姓名字段形成的 `employee_name` |
| 订单配送位置 | 获准保留的 `ship_city`、`ship_region` 和 `ship_country` |
| 供应商 | `company_name`，获准保留的 `city`、`region` 和 `country` |
| 承运商 | `company_name` |
| Gold 客户属性 | `customer_company_name` 及其派生展示值 |
| Gold 员工属性 | `employee_name` 及其派生展示值 |

员工的 `city`、`region` 和 `country` 已被归入 Restricted 并在源端排除，不得因其他表的同名字段被保留而进入平台。

Confidential 字段只能在明确业务用途、已批准数据产品和授权主体范围内使用。普通分析师不得读取客户公司名和员工姓名原值。

### Internal 数据范围

除 Restricted 和 Confidential 之外的已批准源字段及其合规派生结果归类为 Internal，主要包括：

- 源业务标识符
- 订单和订单明细事实
- 商品、品类、库存和停售状态
- 区域与销售区域关系
- 商品交易单价、数量、折扣和运费
- 已确认销售、客户价值、商品、员工和配送代理指标
- 质量结果、对账结果、发布水位和运行元数据

Internal 分类不代表可以公开发布。访问仍受环境、用途、数据层和角色限制。

### 数据产品发布边界

Gold 只发布五类已批准数据产品：

- 每日销售
- 客户价值
- 商品与品类表现
- 员工销售表现
- 配送表现

数据产品不得包含 Restricted 字段。Confidential 字段按批准用途发布，并遵循 Column Mask、最小权限、血缘和审计要求。

当前项目不发布取消、退货、退款、付款、实际送达、准时送达、真实运输时长、承运商最终配送绩效、货币代码或汇率换算结果。

### 分类标签

所有 Catalog、Schema、Table 和关键 Column 使用以下 Governed Tags：

- `data_domain=northwind_sales`
- `classification=restricted|confidential|internal`
- `owner_group=<group_name>`
- `retention_class=<retention_name>`
- `environment=dev|test|prod`
- `certification_status=raw|validated|certified|blocked`

Governed Tags 用于分类、发现、审计和质量检查。当前项目不使用标签自动执行 ABAC 授权。

标签缺失、错误或与字段清单不一致时，不得据此降低权限或解除掩码。分类清单和批准权限仍是权威依据。

## Unity Catalog 权限原则

### 环境隔离

每个环境使用独立 AWS 账户、Databricks Workspace、Catalog、S3 Bucket、KMS Key、运行身份和告警目标。

| 环境 | Catalog | Workspace Binding |
|---|---|---|
| 开发 | `northwind_dev` | 只绑定开发 Workspace |
| 测试 | `northwind_test` | 只绑定测试 Workspace |
| 生产 | `northwind_prod` | 只绑定生产 Workspace |

三个 Workspace 位于同一个 Databricks Account，并绑定东京区域 Unity Catalog Metastore `northwind-tokyo-metastore`。

生产 Catalog 只绑定生产 Workspace。任何跨环境读取、写入、共享、复制或授权都必须作为正式变更单独评审。

### 账户级 Group

| Group | 职责 |
|---|---|
| `grp_northwind_platform` | AWS、Databricks、DMS、存储、网络、调度、监控、恢复和成本 Owner |
| `grp_northwind_engineering` | Pipeline、模型、质量检查、测试和发布实现 |
| `grp_northwind_stewards` | 数据定义、质量规则、分类、异常判定和访问评审 |
| `grp_northwind_analysts` | 使用授权 Gold 数据产品 |
| `grp_northwind_product_owners` | 指标口径、SLA、产品验收和业务发布 Owner |
| `grp_northwind_security` | 安全策略、审计、敏感访问和安全事件 Owner |

Group 在身份提供方中管理并通过账户级 SCIM 同步。

禁止创建 Workspace Local Group。禁止将生产数据权限直接授予个人。临时权限也必须通过受控 Group 或紧急访问流程提供。

### 对象所有权

| 对象 | Owner |
|---|---|
| Unity Catalog Metastore 管理边界 | `grp_northwind_platform` |
| 环境 Catalog | `grp_northwind_platform` |
| `landing`、`bronze`、`silver`、`gold` 和 `ops` Schema | `grp_northwind_platform` |
| Gold 表 | `grp_northwind_product_owners` |
| Column Mask 函数 | `grp_northwind_security` |
| Pipeline 与 Job 实现 | `grp_northwind_engineering` |
| 质量规则定义 | `grp_northwind_stewards` |

Pipeline Service Principal 通过最小写入权限更新 Bronze、Silver、Gold 和 Ops，不获得 Catalog、Schema 或 Gold 表 Owner 权限。

Gold 表 Owner 负责业务发布对象的授权和 Mask 绑定，不得绕过平台和安全治理规则。

### 分层访问矩阵

| 数据层 | 写入主体 | 读取主体 | 禁止主体 |
|---|---|---|---|
| DMS 落地区 | DMS 专用 IAM Role | Databricks Landing Role | 平台组、工程组、分析师、产品用户和个人 AWS 身份 |
| Landing Volume | 无 Databricks 写入 | Pipeline Service Principal，平台和工程按排障需要读取 | Steward、产品 Owner、分析师默认无访问 |
| Bronze | Pipeline Service Principal | 平台、工程和 Steward | 分析师和普通产品用户 |
| Silver | Pipeline Service Principal | 平台、工程和 Steward | 分析师和普通产品用户 |
| Gold | Pipeline Service Principal | 产品 Owner、Steward 和授权分析师 | 未授权主体 |
| Ops | Pipeline Service Principal，平台和工程按职责写入 | 平台、工程、Steward 与安全组按职责读取 | 普通分析师 |

分析师只通过 Gold 和批准的 SQL Warehouse 使用数据，不直接读取 Landing、Bronze、Silver 或 Ops。

平台排障访问必须保持只读优先。需要写入或修复时必须使用受控运行身份和已批准变更，不得直接修改源文件、Bronze 原始事件或认证 Gold 结果。

### 运行身份与职责分离

| 平台 | 身份 | 用途 |
|---|---|---|
| PostgreSQL | `dms_northwind_<environment>` | 读取 14 张源表和逻辑复制 |
| AWS IAM | `role-northwind-dms-s3-<environment>` | DMS 写入落地 Bucket 并使用 DMS KMS Key |
| AWS IAM | `role-northwind-dms-secret-<environment>` | DMS 读取指定 Secrets Manager Secret |
| AWS IAM | `role-northwind-databricks-landing-read-<environment>` | Databricks 只读 DMS 落地区 |
| AWS IAM | `role-northwind-databricks-uc-managed-<environment>` | Unity Catalog 读写对应环境托管存储 |
| Databricks | `sp_northwind_pipeline_<environment>` | Pipeline、Job、质量检查和 Gold 发布 |
| Databricks | `sp_northwind_deploy_<environment>` | 受控发布 Terraform 和 Asset Bundles |

生产 Job 和 Pipeline 必须由运行 Service Principal 执行，不得由个人用户运行。

部署 Service Principal 不读取业务表。运行 Service Principal 不拥有 IAM、KMS、网络、Workspace 或基础设施管理权限。

Databricks 自动化使用 OAuth 机器到机器认证，不使用个人访问令牌。AWS 服务访问使用专用 IAM Role，不使用 IAM User。

RDS 凭证只存储在 AWS Secrets Manager 专用 Secret。代码、Notebook、配置、质量结果、日志、告警和文档不得输出凭证值。

### 列级保护

- `customer_company_name` 对产品 Owner 和 Steward 显示原值，对普通授权分析师显示基于 `customer_id` 的稳定别名。
- `employee_name` 对产品 Owner 和 Steward 显示原值，对普通授权分析师显示基于 `employee_id` 的稳定别名。
- 列级保护统一使用 Unity Catalog 表级 Column Mask。
- Mask 函数由 `grp_northwind_security` 管理，Gold 表 Owner 负责绑定。
- 稳定别名只包含对象类型和源标识符，不包含姓名、公司名、Secret 或可逆加密值。
- 当前项目不使用 Dynamic View 承担字段脱敏。
- 当前项目不使用 ABAC Policy。
- 当前项目不实施行级过滤，因为源 Schema 没有可验证的组织访问边界字段。

Mask 规则、授权 Group 或字段分类发生变化时，必须重新执行授权与未授权主体测试。

### 访问申请与审批

生产访问必须满足以下条件：

1. 申请中明确业务用途、所需数据产品、所需权限和有效期
2. 产品 Owner 确认业务用途
3. 安全 Owner 确认数据分类和敏感访问
4. 平台 Owner 通过账户级 Group 实施授权
5. 审计记录包含申请、批准、实施和验证证据

生产访问禁止永久授予没有持续业务用途的主体。

客户公司名和员工姓名原值访问固定授予产品 Owner 与 Steward。安全 Owner 负责批准和审计敏感访问，不自动获得业务原值读取权限。安全事件需要查看原值时必须使用受控紧急访问流程。

### 访问评审与撤权

- 生产访问每季度评审一次。
- 评审固定在一月、四月、七月和十月的前五个工作日完成。
- 评审覆盖账户级 Group 成员、Service Principal、Catalog Binding、Storage Credential、External Location、Volume、Table、Column Mask 和紧急访问记录。
- 离职、转岗、项目退出和业务用途终止触发即时撤权。
- 发现个人直授权、Workspace Local Group、跨环境授权或超出用途的权限时立即撤销并记录整改。
- 未完成季度评审的生产访问视为治理失败，必须升级平台 Owner 和安全 Owner。

### 紧急访问

紧急访问最长有效 8 小时，必须记录：

- 事件编号
- 申请人和执行身份
- 批准人
- 访问用途
- 目标环境和对象
- 开始与到期时间
- 实际操作范围
- 撤权确认
- 审计证据位置

紧急访问不得用于绕过 Restricted 字段排除、生产环境隔离、Column Mask、审计投递或发布门禁。

## 数据保留与删除要求

### 保留期

| 数据 | 保留期 |
|---|---|
| DMS 落地文件 | 365 天 |
| Bronze CDC 历史 | 400 天 |
| Silver 当前状态 | 项目有效期内持续保留，项目终止后 90 天删除 |
| Gold 销售明细与聚合 | 7 年 |
| 商品库存观察快照 | 3 年 |
| 隔离记录 | 90 天 |
| Schema 漂移事件 | 400 天 |
| 对账和质量结果 | 400 天 |
| Pipeline 内部状态 | Pipeline 有效期内持续保留 |
| Job 与 Pipeline 运行元数据 | 400 天 |
| 发布水位与认证状态 | 400 天 |
| AWS 与 Databricks 审计日志 | 400 天 |

保留期从对象创建时间、业务快照日期或运行完成时间起算，具体起点按对象类型固定并写入实施设计。

任何实现不得使用短于本文的保留期。延长保留期必须同时评估成本、安全、删除义务和恢复价值。

### S3 生命周期

DMS 落地文件前 90 天保持 S3 Standard，用于标准重跑窗口和 4 小时常规 RTO。

91 至 365 天转入 S3 Glacier Flexible Retrieval，满 365 天删除。归档恢复不计入常规 4 小时 RTO。

| Bucket | Versioning 决策 |
|---|---|
| DMS 落地区 | 关闭，使用不可变对象名和数据代际实现重放隔离 |
| Unity Catalog 托管存储 | 关闭，由 Delta Lake 管理表版本和清理 |
| 审计日志 | 开启，并启用 S3 Object Lock Governance |

DMS 落地文件视为不可变对象，禁止人工覆盖、改写或移动。发现同键覆盖行为时立即阻断任务并升级为 Sev 2。

Unity Catalog 托管数据不得通过 S3 Lifecycle 直接删除 Delta 文件。Lakeflow 内部状态不得配置对象生命周期删除。

生命周期策略不得删除当前 90 天标准补数窗口所需的数据，也不得破坏正在使用的数据代际。

### Delta 保留

- Delta 删除文件保留期固定为 30 天。
- Delta 事务日志保留期固定为 400 天。
- 任何 `VACUUM` 不得使用短于 30 天的保留期。
- 受控重跑、对账、恢复和法定删除必须评估 Delta 历史与物理文件状态。
- 禁止以节省存储成本为由提前清理仍处于恢复、审计或调查范围的数据。

### 源端删除传播

源端 DELETE 事件目标在 15 分钟内从 Silver 当前状态和后续 Gold 刷新中移除。

Bronze 和 DMS 落地区保留历史删除事件，保留期分别为 400 天和 365 天，用于恢复、对账和审计。

源端删除传播失败或超过 30 分钟时，受影响 Gold 产品不得认证，必须创建 Critical 告警并进入事件处置。

源端 DELETE 不等同于法定删除。历史事件是否需要物理清理由法定删除流程决定。

### 法定删除

收到具有法律效力的数据删除指令时，由 `grp_northwind_security` 启动例外删除流程。

删除范围至少覆盖：

- DMS 落地区
- Landing 可见对象
- Bronze
- Silver
- Gold
- Ops 隔离记录中的受影响内容
- 导出副本
- 查询结果缓存
- 下游批准副本

例外删除流程必须记录：

1. 指令来源和法律依据
2. 受影响主体和业务键
3. 受影响环境、数据层、对象和日期范围
4. 备份、归档和缓存影响
5. 执行身份和批准人
6. 删除开始与完成时间
7. 物理清理和逻辑不可见验证
8. 下游通知和副本确认
9. 后续重跑、补数和数据代际重建不会重新引入已删除数据的验证
10. 不含被删除内容的执行审计记录

删除完成前，受影响数据产品的发布和导出范围必须由安全 Owner 评估。

### 项目终止与数据销毁

项目终止时，产品 Owner、平台 Owner、Steward 和安全 Owner 共同确认终止日期、法定保留义务、下游依赖、导出副本和销毁顺序。

Silver 当前状态在项目终止后保留 90 天并删除。Gold、审计和其他长期数据继续遵循各自保留期，除非法定删除或正式变更另有要求。

销毁操作必须保留不含业务数据的执行证据，并验证 Catalog 授权、Storage Credential、External Location、Volume、S3 对象、KMS 授权和运行身份已经按范围撤销。

### 保留与删除变更

保留期、S3 Lifecycle、Delta 属性、删除传播目标或法定删除流程变更需要以下主体共同批准：

- `grp_northwind_product_owners`
- `grp_northwind_platform`
- `grp_northwind_stewards`
- `grp_northwind_security`

变更必须评估 SLA、RTO、标准补数窗口、成本、安全、审计和下游兼容性。

## 调度、SLA 与 Owner

### 时间与区域

| 项目 | 已确认值 |
|---|---|
| AWS 区域 | `ap-northeast-1` |
| 调度时区 | `Asia/Tokyo` |
| 运行与审计时间 | UTC |
| 源日期类型 | 保持 `DATE` |
| 源日期时区处理 | 不进行时区换算 |
| 环境 | `dev`、`test`、`prod` |

RDS、DMS、S3 和 Databricks Workspace 必须位于 `ap-northeast-1`。跨区域灾难恢复不在当前项目范围。

### 事件驱动调度

编排 Job 名称模式为 `northwind-sales-<environment>-orchestration`。

| 项目 | 已确认值 |
|---|---|
| 主触发方式 | File Arrival Trigger |
| 监控位置 | 当前数据代际 DMS 落地根路径 |
| 最小触发间隔 | 5 分钟 |
| 文件静默等待 | 60 秒 |
| Pipeline 模式 | Triggered |
| 最大并发运行 | 1 |
| 队列 | 启用 |
| 自动重试 | 3 次 |
| 重试间隔 | 5 分钟 |
| 单次运行超时 | 60 分钟 |

Job 执行顺序固定为：

1. 启动 ingestion Pipeline 并处理当前可用文件
2. 执行关键数据质量检查
3. 刷新五类 Gold 数据产品
4. 执行指标对账和发布门禁
5. 更新 `ops.publish_watermarks` 和 `ops.job_runs`
6. 发送成功、失败、超时、积压和质量通知

任何步骤失败时停止后续发布。失败运行不得推进 Gold 认证水位。

同一 Pipeline Update 只允许一个活动实例。队列可以等待，不得并发写入同一受影响 Gold 范围。

### 日终认证

日终 Job 名称模式为 `northwind-sales-<environment>-daily-certification`。

| 项目 | 已确认值 |
|---|---|
| 启动时间 | 每日 01:30 `Asia/Tokyo` |
| 销售认证截止 | 前一东京日历日期 |
| 完成目标 | 02:00 `Asia/Tokyo` 前 |
| 标准补数窗口 | 最近 90 天 |
| 超过 90 天补数 | 产品 Owner 和平台 Owner 双重批准 |

日终认证即使没有新文件也必须执行，用于刷新客户价值快照、商品库存观察快照、配送开放订单天数、对账和认证状态。

每日销售和客户价值使用前一东京日历日期。商品库存观察快照使用 Job 运行时的东京日历日期并记录实际 UTC 观察时间。

### SLA 与恢复目标

| 指标 | 已确认目标 |
|---|---|
| 端到端数据新鲜度 P95 | 源提交后 15 分钟内进入 Gold |
| 最大允许延迟 | 30 分钟 |
| 日终认证完成 | 每日 02:00 `Asia/Tokyo` 前 |
| 月度数据产品可用性 | 99.5 百分比 |
| RPO | 5 分钟 |
| RTO | 4 小时 |
| 标准补数窗口 | 90 天 |
| 源端删除传播目标 | 15 分钟 |

正常 CDC 新鲜度从 `_dms_commit_ts` 到 Gold `last_refreshed_at_utc` 计算。Full Load 记录不参与正常 CDC 新鲜度统计。

Gold 新鲜度超过 30 分钟时不得认证发布。超过目标的新到数据仍要处理，并记录 SLA 违约、影响范围和迟到原因。

月度可用性按计划认证窗口中成功保持 `certified` 状态的分钟数除以计划服务分钟数计算。

提前公告并获得产品 Owner 与平台 Owner 批准的维护窗口不计入计划服务分钟数。未批准维护、权限错误、成本停机、质量门禁失败和平台故障均计入可用性影响。

RPO 由 DMS 300 秒最大批次间隔、PostgreSQL 逻辑复制槽和 S3 不可变落地共同支撑。

RTO 适用于区域内常规故障和最近 90 天在线数据，不包括 Glacier 归档恢复和跨区域灾难。

### 发布状态

每个 Gold 数据产品使用以下受控发布状态：

- `candidate`
- `certified`
- `blocked`

只有适用关键质量规则全部通过、增量对账成功、Restricted 扫描结果为零、认证数据没有未处理的 `_rescued_data`，并且数据新鲜度未超过 30 分钟时，产品状态才能更新为 `certified`。

关键失败时，受影响产品更新为 `blocked`。失败运行不得覆盖最近一次已认证结果，也不得推进认证水位。

### Owner 职责

| 事项 | 最终责任 |
|---|---|
| 业务指标、产品范围和数据产品验收 | `grp_northwind_product_owners` |
| 平台架构、SLA、调度、监控、故障恢复和成本 | `grp_northwind_platform` |
| Pipeline、数据模型、质量检查和发布实现 | `grp_northwind_engineering` |
| 数据定义、质量规则、分类和异常判定 | `grp_northwind_stewards` |
| 安全策略、审计、敏感访问和安全事件 | `grp_northwind_security` |
| 日常分析使用 | `grp_northwind_analysts` |

Owner 指账户级 Group，不代表真实个人联系方式。值班人员、审批人和业务联系人必须从组织的受控目录和事件管理系统读取。

### 运行职责分工

| 场景 | 平台 | 工程 | Steward | 产品 Owner | 安全 |
|---|---|---|---|---|---|
| Pipeline 失败 | 创建事件并恢复平台 | 定位并修复实现 | 评估数据影响 | 确认业务影响和恢复发布 | 按需参与 |
| 关键质量失败 | 触发告警并阻断发布 | 修复解析或模型问题 | 判定规则和数据处置 | 确认产品恢复 | 涉及敏感数据时参与 |
| Restricted 命中 | 停止发布并保护环境 | 支持范围定位 | 支持字段确认 | 接收业务影响通知 | 主导安全事件 |
| SLA 违约 | 创建事件并恢复服务 | 支持技术修复 | 评估数据完整性 | 确认业务影响 | 涉及审计或权限时参与 |
| 超过 90 天补数 | 评估恢复和成本 | 执行受控重算 | 验证数据规则 | 批准补数范围 | 涉及敏感或删除时参与 |
| 权限申请 | 实施授权 | 无默认职责 | 参与用途评审 | 批准业务用途 | 批准敏感访问 |
| 成本超限 | 主导分析和优化 | 优化作业与模型 | 评估保留影响 | 批准预算或服务调整 | 评估安全影响 |

### 审批规则

- 指标口径变更需要产品 Owner 和 Steward 批准。
- 源字段纳入或排除需要产品 Owner、Steward 和安全 Owner 批准。
- SLA 和成本预算变更需要产品 Owner 与平台 Owner 批准。
- 保留期和删除流程变更需要产品 Owner、平台 Owner、Steward 和安全 Owner 共同批准。
- 生产访问需要产品 Owner 和安全 Owner 批准。
- 源 Schema 变更需要工程、平台和 Steward 完成影响评估后由产品 Owner 批准。
- 告警阈值、重试、超时、补数窗口和恢复顺序变更需要平台 Owner 批准，并由产品 Owner 评估 SLA 影响。

## 监控、告警与升级路径

### 告警渠道

| 渠道 | 已确认值 |
|---|---|
| AWS SNS Topic 模式 | `northwind-data-<environment>-alerts` |
| Databricks System Destination 模式 | `northwind-data-<environment>-ops` |
| 主要接收方 | 平台值班事件管理系统 |
| 业务升级接收方 | `grp_northwind_product_owners` |
| 安全升级接收方 | `grp_northwind_security` |
| 通知目标编号 | 部署运行变量 `notification_destination_id` |

AWS CloudWatch 通过 SNS 投递 DMS、RDS、S3、KMS 和成本告警。

Databricks Job 与 Pipeline 通过 System Destination 投递失败、超时、积压、质量和新鲜度告警。

两个渠道必须进入同一平台值班事件流并生成可追踪事件编号。文档和代码不得写入真实个人电话号码、邮箱或通知目标编号。

### 必须监控的指标

#### AWS 与源端

- DMS Replication State
- DMS Full Load 表完成、失败和挂起数量
- DMS CDC Source Latency
- DMS CDC Target Latency
- DMS 当前和最大 DCU
- PostgreSQL Replication Slot Disk Usage
- PostgreSQL WAL 保留量
- RDS FreeStorageSpace
- WAL Heartbeat 推进时间
- S3 写入错误、拒绝请求和对象数量
- KMS 加密与解密拒绝
- Secrets Manager 读取失败和轮换状态
- AWS 审计日志最后投递时间
- AWS 实际和预测成本

#### Databricks 与数据链路

- Auto Loader 待处理文件数
- Auto Loader 待处理字节数
- Auto Loader 最老文件时间
- Pipeline 运行时长、失败次数和 Flow 状态
- Pipeline 自动重试次数
- Gold 新鲜度和认证水位
- 数据质量关键失败数
- `_rescued_data` 记录数
- Restricted 字段扫描结果
- 持久外键孤儿数
- Silver 主键重复数
- Gold 粒度重复数
- 对账差异状态
- SQL Warehouse 队列、运行时长和利用率
- Databricks 审计日志最后投递时间
- Databricks 实际和预测成本

### 摄取与平台阈值

| 监控项 | Warning | Critical |
|---|---|---|
| DMS CDC Source Latency | 超过 10 分钟 | 超过 20 分钟 |
| DMS CDC Target Latency | 超过 10 分钟 | 超过 20 分钟 |
| DMS Replication State | 状态异常持续 2 分钟 | 停止、失败或错误持续 5 分钟 |
| DMS Full Load 表状态 | 单表出现警告 | 失败表或挂起表大于零 |
| DMS DCU 使用 | 达到最大 DCU 持续 15 分钟 | 达到最大 DCU 持续 30 分钟并伴随延迟 |
| PostgreSQL 复制槽保留 WAL | 达到 RDS 分配存储的 10 百分比 | 达到 RDS 分配存储的 20 百分比 |
| RDS FreeStorageSpace | 低于 20 百分比 | 低于 10 百分比 |
| WAL Heartbeat | 10 分钟没有推进 | 20 分钟没有推进 |
| S3 或 KMS Access Denied | 单次事件 | 连续事件或影响生产写入 |
| Auto Loader 最老待处理文件 | 超过 10 分钟 | 超过 20 分钟 |
| Auto Loader 待处理字节 | 连续两次运行增长 | 连续四次运行增长并超过 SLA |
| 审计日志投递间隔 | 超过 15 分钟 | 超过 30 分钟 |

### 作业、质量与发布阈值

| 监控项 | Warning | Critical |
|---|---|---|
| Pipeline 运行 | 首次失败 | 三次自动重试后仍失败 |
| Pipeline 运行时长 | 超过 45 分钟 | 超过 60 分钟 |
| Gold 数据新鲜度 | 超过 20 分钟 | 超过 30 分钟 |
| 关键数据质量失败数 | 不适用 | 大于零 |
| `_rescued_data` | 任一运行大于零 | 连续两次运行大于零或涉及认证字段 |
| Restricted 字段扫描 | 不适用 | 发现任一 Restricted 源列进入平台或任一 Restricted 源值进入未批准输出 |
| 持久外键孤儿 | 宽限期间记录并监控 | 超过 30 分钟仍大于零 |
| Silver 主键重复 | 不适用 | 大于零 |
| Gold 粒度重复 | 不适用 | 大于零 |
| 无法解释的对账差异 | 首次发现并进入调查 | 发布前仍未解释 |
| 日终认证 | 01:50 前未完成 | 02:00 前未完成 |
| 月度实际或预测成本 | 达到预算 80 百分比 | 达到预算 100 百分比 |

预算达到 50 百分比时生成信息通知，不计入 Warning。

### 故障等级

| 等级 | 条件 | 响应目标 |
|---|---|---|
| Sev 1 | 数据丢失、敏感数据泄露、Restricted 字段进入平台、不可恢复数据损坏 | 15 分钟内确认，立即升级平台和安全 Owner |
| Sev 2 | 新鲜度超过 30 分钟、Job 重试后仍失败、DMS 停止、日终认证失败、关键质量门禁失败、审计中断 | 30 分钟内确认，4 小时内恢复 |
| Sev 3 | Schema 漂移、非关键质量警告、可解释的非阻断对账偏差、成本 Warning、单个非认证报表问题 | 下一个工作日处理 |

Critical 告警必须创建值班事件。

Restricted 字段扫描命中、疑似数据泄露和不可恢复数据损坏直接按 Sev 1 处理。

升级顺序固定为平台值班、平台 Owner、产品 Owner。涉及敏感数据、权限或审计时同时通知安全 Owner。

### 事件处置流程

每个 Critical 事件至少执行以下步骤：

1. 创建唯一事件编号
2. 确认环境、数据代际、受影响表、受影响产品和当前水位
3. 判断是否停止 DMS、Pipeline、Gold 发布或用户访问
4. 保留只读诊断证据
5. 执行已批准 Runbook
6. 完成恢复、重跑、对账和质量验证
7. 由产品 Owner 确认业务恢复
8. 涉及安全时由安全 Owner 确认安全恢复
9. 更新事件时间线、根因、影响和后续行动
10. 保留事件、告警、运行和验证证据

事件未完成质量和对账验证前，不得将受影响产品恢复为 `certified`。

### Runbook 最低要求

每个 Critical 告警必须有对应 Runbook，至少包含：

- 适用监控项和触发条件
- 影响判断
- 只读诊断步骤
- 停止发布条件
- 恢复步骤
- 回滚步骤
- 对账步骤
- Owner 与升级路径
- 证据留存位置
- 验证完成条件

Runbook 不得要求手工删除 Lakeflow 内部状态、修改源数据、覆盖 DMS 落地文件、静默修改 Bronze、绕过 Unity Catalog 权限或跳过发布门禁。

### 血缘与审计

- Unity Catalog 血缘覆盖 Landing、Bronze、Silver、Gold、Pipeline 和 Job。
- Databricks 账户级审计日志以 JSON 投递到审计 Bucket。
- 生产审计证据以账户级审计日志投递为准。
- Audit System Table 只作为可用时的辅助查询来源。
- CloudTrail 记录 S3、KMS、Secrets Manager、IAM 和 DMS 管理事件。
- 生产 S3 Bucket 启用 CloudTrail 数据事件。
- AWS 与 Databricks 审计日志保留 400 天。
- 审计 Bucket 使用 Object Lock Governance 防止保留期内篡改。
- 审计日志读取只授予 `grp_northwind_security` 和受控审计身份。
- 审计日志不得记录 Secret、密码、令牌或 Restricted 原值。

审计日志投递超过 15 分钟生成 Warning，超过 30 分钟生成 Critical。审计中断按 Sev 2 处理。

## 重跑、补数与故障恢复

### 基本原则

- 重跑必须幂等。
- 重跑不得修改 Landing 文件或 Bronze 原始事件。
- 重跑不得手工删除、移动或编辑 Lakeflow Checkpoint 和 Auto Loader Schema State。
- 重跑必须使用批准的数据代际和确定性排序规则。
- 重跑必须限制在实际受影响表、业务键、日期、快照和依赖产品范围内。
- 重跑不得推进早于最近认证水位的输出水位。
- 重跑完成后必须重新执行关键质量检查、对账和发布门禁。
- 失败重跑不得覆盖最近一次已认证结果。

### 重跑类型

| 类型 | 使用场景 | 约束 |
|---|---|---|
| 原运行重试 | 短暂平台故障或可恢复任务失败 | 使用原 Pipeline 状态和原数据代际 |
| 失败对象刷新 | 单个 Flow 或依赖对象失败 | 只刷新失败对象及依赖，禁止清空全局状态 |
| Gold 定向重算 | 业务字段更正或历史日期受影响 | 确定性覆盖受影响日期、业务键或快照 |
| 标准历史补数 | 最近 90 天内的迟到、更正或重算 | 使用在线 Landing、Bronze 或 Silver 数据 |
| 受控历史补数 | 超过 90 天的更正或归档恢复 | 需要产品 Owner 和平台 Owner 双重批准 |
| 受控 Full Refresh | Pipeline 状态不可恢复且当前代际文件完整 | 先验证源文件完整性和重放范围 |
| 新数据代际重建 | 当前代际不完整、污染或 DMS 无法续接 | 新建 Full Load 加 CDC，完成验证后原子切换 |

### 业务更正与重算范围

以下源变化必须触发受影响 Gold 结果重算：

- `shipped_date` 从空值变为日期
- `shipped_date` 从日期变为空值
- `shipped_date` 改为其他日期
- 订单客户变化
- 订单员工变化
- 订单运费变化
- 订单明细商品变化
- 订单明细交易单价变化
- 订单明细数量变化
- 订单明细折扣变化
- 当前客户、员工、商品、品类、供应商或承运商属性变化

`shipped_date` 从空值变为日期时，订单进入认证销售。

`shipped_date` 从日期变为空值时，订单从认证销售移除。

`shipped_date` 改为其他日期时，原销售日期和新销售日期都必须重算。

当前属性变化可以重述历史展示属性，但不得改变稳定源标识符和已确认业务归属规则。

### 恢复顺序

恢复顺序固定为：

1. DMS 故障优先使用原任务和原 PostgreSQL 逻辑复制槽恢复
2. Pipeline 故障优先使用原 Lakeflow 内部 Checkpoint 重试失败 Flow
3. 使用 Lakeflow 支持的失败对象刷新能力重跑失败对象及依赖
4. Checkpoint 异常时先在非生产验证受支持的恢复操作
5. 当前数据代际完整时，对受影响 Bronze 和依赖 Silver 执行受控 Full Refresh
6. 当前代际不完整或 DMS 无法安全续接时，创建新数据代际并执行 Full Load 加 CDC
7. Silver 从完整 Bronze 或新数据代际重建
8. Gold 从 Silver 重建
9. 完成行数、主键、外键、金额和 CDC 连续性对账
10. 通过发布门禁后原子切换认证引用

禁止在未验证源文件完整性时执行 Full Refresh。

### 数据代际切换

创建新数据代际时必须满足：

- 新代际使用受控递增标识
- 旧代际立即转为只读
- DMS Full Load 和 CDC 连续性通过验证
- 14 张源表全部完成且无失败表或挂起表
- 62 个批准字段与白名单一致
- Restricted 字段扫描结果为零
- Silver 主键唯一
- 持久外键孤儿为零
- 金额、运费和五类产品对账通过
- 新代际水位完整记录
- 发布门禁通过
- 认证引用通过原子方式切换

旧代际删除遵循 DMS 落地 365 天和 Bronze 400 天保留策略，不得因新代际上线而提前清理。

### RPO 与 RTO

RPO 为 5 分钟。任何可能超过 RPO 的 DMS 停止、复制槽异常、S3 写入失败或数据丢失风险必须立即升级。

RTO 为 4 小时，适用于区域内常规故障和最近 90 天在线数据。

以下场景不纳入常规 4 小时 RTO：

- 91 天后的归档恢复
- 跨区域灾难

### 恢复与补数证据

每次重跑、补数、Full Refresh 或数据代际切换至少记录：

- 事件或变更编号
- 触发原因
- 环境
- 数据代际
- 受影响表、业务键、日期和产品
- 输入文件和输入水位
- 执行身份
- 开始与结束 UTC 时间
- 重跑类型
- 质量结果
- 对账结果
- 输出水位
- 发布状态
- 批准人
- 证据位置

超过 90 天的补数必须同时记录归档恢复时间、额外成本和 RTO 例外。

### 演练要求

首次生产发布前必须完成以下演练：

- DMS 停止和恢复
- Pipeline 自动重试和失败对象刷新
- 重复文件与幂等处理
- 乱序 CDC
- DELETE 和删除后重插
- Checkpoint 异常的非生产恢复验证
- 受控 Full Refresh
- 新数据代际重建与原子切换
- 最近 90 天补数
- Gold 发布门禁失败与最近认证结果保留
- RPO 和 RTO
- 告警渠道到达
- 审计证据留存

这些条目是验收要求，不表示当前环境已经完成演练或通过。

## 成本边界与监控

### 计算资源边界

| 工作负载 | 已确认计算方式 |
|---|---|
| Bronze 与 Silver | Serverless Lakeflow Declarative Pipeline |
| Gold 刷新与质量任务 | Serverless Jobs |
| BI 与交互查询 | Serverless SQL Warehouse |
| 开发探索 | Serverless 或受策略约束的标准访问计算 |

生产 SQL Warehouse 名称固定为 `northwind-sales-prod-bi`。

| 参数 | 已确认值 |
|---|---|
| 初始大小 | `2X-Small` |
| 最小集群数 | 1 |
| 最大集群数 | 1 |
| 自动停止 | 空闲 10 分钟 |
| Channel | Standard |
| Serverless | 启用 |

项目禁止使用 Preview、Beta、实验性或私有预览能力。

DMS Serverless 最小容量为 1 DCU，最大容量为 16 DCU。提高最大容量必须完成成本和 SLA 评审。

### 月度预算

预算是治理上限，不代表真实生产成本预测，也不保证预算一定充足。

| 环境 | 月度预算上限 |
|---|---:|
| `prod` | 500 USD |
| `test` | 100 USD |
| `dev` | 100 USD |
| 合计 | 700 USD |

AWS Budgets 和 Databricks 账单使用量必须同时监控实际成本与预测成本。

### 预算阈值与动作

| 阈值 | 等级 | 必须动作 |
|---|---|---|
| 预算 50 百分比 | 信息 | 检查月内进度、异常增长和成本标签完整性 |
| 预算 80 百分比 | Warning | 平台 Owner 在两个工作日内完成成本分析和优化计划 |
| 预算 100 百分比 | Critical | 暂停非生产按需任务，生产继续满足 SLA，由平台 Owner 和产品 Owner 批准预算或资源调整 |

成本告警必须覆盖 AWS 实际与预测成本、Databricks 实际与预测使用量、DMS DCU、S3 存储与请求、Pipeline、Jobs、SQL Warehouse、网络和日志成本。

### 成本基线

生产启用后的前 30 天作为真实成本基线期。

基线报告至少拆分：

- RDS 增量负载
- DMS DCU
- S3 存储
- S3 请求
- Databricks Pipeline
- Databricks Jobs
- SQL Warehouse
- 网络
- 审计与运行日志

Northwind 样例数据不能作为生产容量、峰值、增长率或预算充足性的证明。

30 天后只能通过变更控制调整预算、DMS 最大 DCU、SQL Warehouse 大小、触发频率、文件策略和保留期。

### 优化顺序

成本优化必须保持数据完整性、SLA、RPO、RTO、重放能力、审计和安全边界。

优化顺序固定为：

1. 消除失败重试、重复扫描和无效计算
2. 限制 Gold 重算到受影响日期、业务键和快照
3. 优化数据模型、扫描范围、查询和文件布局
4. 验证 SQL Warehouse 自动停止和队列行为
5. 检查 DMS LOB、文件刷新和目标写入参数
6. 检查 S3 Lifecycle、日志量和非生产资源运行时间
7. 通过变更评审调整 Warehouse 大小、最大集群数、DMS 最大 DCU 或调度频率

禁止通过以下方式降低成本：

- 缩短已确认保留期
- 跳过质量检查或对账
- 关闭审计日志
- 删除最近 90 天重跑所需数据
- 降低 Restricted 扫描范围
- 绕过环境隔离
- 使用个人身份运行生产作业
- 提前清理 Lakeflow 内部状态

### 成本标签

所有 AWS 和 Databricks 资源使用以下成本标签：

- `project=northwind-sales`
- `environment=dev|test|prod`
- `owner=grp_northwind_platform`
- `cost_center=data-platform`
- `managed_by=iac`

无成本标签的资源不得进入生产发布。

标签完整性必须纳入部署门禁和月度成本检查。

### 成本审批

- 月度预算变更需要产品 Owner 与平台 Owner 批准。
- DMS 最大 DCU 提升需要平台 Owner 批准并完成成本评审。
- SQL Warehouse 扩容需要平台 Owner 批准，并先证明模型和查询优化不足以解决问题。
- 保留期变更不能只以成本为依据，必须完成产品、平台、Steward 和安全联合审批。
- 预算达到 100 百分比时，生产服务不得因自动成本控制而违反已确认 SLA。

## 运维证据与记录

### Ops 对象

| Ops 对象 | 用途 | 保留期 |
|---|---|---|
| `ops.pipeline_run_metrics` | Pipeline Event Log 的受控运行视图 | 400 天 |
| `ops.data_quality_results` | 质量规则结果、失败数量、范围和状态 | 400 天 |
| `ops.source_reconciliation` | 源到各层和产品间对账结果 | 400 天 |
| `ops.quarantine_records` | 隔离记录和处置证据 | 90 天 |
| `ops.schema_drift_events` | Schema 漂移事件 | 400 天 |
| `ops.publish_watermarks` | 输入水位、输出水位和认证状态 | 400 天 |
| `ops.job_runs` | Job 和 Pipeline 运行证据 | 400 天 |

每次发布至少记录：

- 环境
- 数据代际
- Pipeline 更新标识
- Job 运行标识
- 执行身份
- 输入水位
- 输出水位
- 源文件数量
- Bronze 行数
- Silver 变更数
- Gold 行数
- 质量状态
- 对账状态
- Restricted 扫描结果
- `_rescued_data` 状态
- 发布状态
- 开始与结束 UTC 时间
- 告警和事件引用
- 证据位置

只有真实运行记录可以证明作业、质量检查、发布、告警、恢复或成本控制已经执行。

### 密钥与凭证治理

- RDS 凭证存储在 AWS Secrets Manager 专用 Secret。
- Secret 只包含 DMS 需要的 Host、Port、Username 和 Password。
- Secrets Manager 凭证每 90 天轮换一次。
- KMS 客户管理密钥启用自动轮换。
- DMS 落地区及其 Landing External Volume 使用项目 DMS KMS Key。
- Unity Catalog 托管存储使用项目 UC KMS Key。
- 审计 Bucket 使用项目审计 KMS Key。
- 三类 KMS Key 相互隔离并启用自动轮换。
- Secret 轮换后必须执行 DMS 端点连接测试和 Pipeline 只读连接测试。
- 凭证值不得进入代码、Notebook、配置、文档、日志、告警、质量结果或工单。

### 安全验收

生产发布前必须由安全 Owner 验证：

- S3 Block Public Access 全部启用
- Bucket Policy 和 KMS Key Policy 符合最小权限
- VPC Endpoint Policy 只覆盖批准资源
- Restricted 字段扫描结果为零
- Column Mask 对授权与未授权主体结果正确
- 生产无个人直授权和 Workspace Local Group
- 审计日志持续投递并受 Object Lock Governance 保护
- 紧急访问和季度评审流程可执行
- 真实凭证未进入代码、日志或文档

以上项目是验收要求，不表示当前环境已经通过。

## 变更控制与状态边界

### 需要正式变更的事项

以下变化必须更新本文并完成相应审批：

- Restricted、Confidential、Internal 或 Public 分类变化
- 源字段纳入或排除变化
- Unity Catalog Group、Owner、权限、Mask、Binding 或访问流程变化
- S3、Delta、Gold、审计或 Ops 保留期变化
- 源端删除传播或法定删除流程变化
- 调度频率、重试、超时、并发或日终认证时间变化
- SLA、RPO、RTO、可用性计算或维护窗口规则变化
- 告警渠道、阈值、严重等级、响应目标或升级路径变化
- 重跑类型、标准补数窗口、恢复顺序或数据代际规则变化
- 月度预算、成本阈值、计算资源或成本标签变化
- Owner 和审批责任变化

变更必须评估源映射、DMS、S3、Auto Loader、Bronze、Silver、Gold、Ops、数据产品、质量、权限、血缘、审计、重跑、恢复、SLA、成本和下游兼容性。

旧规则是否失效必须明确记录。不得静默覆盖已经被历史运行、质量结果、发布水位或审计记录引用的规则版本。

### 部署运行变量

以下值必须从真实环境或受控部署参数读取，不得在本文中填写看似真实的值：

| 变量 | 获取规则 |
|---|---|
| `aws_account_id` | 从目标 AWS 账户身份读取 |
| `environment` | 只能取 `dev`、`test`、`prod` |
| `rds_endpoint` | 从目标 RDS 资源清单读取 |
| `rds_database` | 从受控部署参数读取 |
| `dms_kms_key_arn` | 从批准的 KMS Alias 解析 |
| `uc_kms_key_arn` | 从批准的 KMS Alias 解析 |
| `audit_kms_key_arn` | 从批准的 KMS Alias 解析 |
| `databricks_workspace_id` | 从目标 Workspace 读取 |
| `databricks_metastore_id` | 从东京区域 Unity Catalog Metastore 读取 |
| `notification_destination_id` | 从批准的平台值班通知目标读取 |

部署运行变量不改变本文的治理和运维合同。

### 当前确认状态

当前没有阻断治理或运维设计的开放事项。

本文已固定以下项目决策：

- 30 个 Restricted 字段在 DMS 字段白名单阶段排除
- Confidential 字段按批准用途发布并使用 Column Mask
- 生产权限只授予账户级 Group 和专用 Service Principal
- 开发、测试和生产环境严格隔离
- 审计日志保留 400 天
- Gold 销售数据保留 7 年
- 商品库存观察快照保留 3 年
- 标准补数窗口为 90 天
- P95 新鲜度目标为 15 分钟
- 最大允许延迟为 30 分钟
- RPO 为 5 分钟
- RTO 为 4 小时
- 月度数据产品可用性目标为 99.5 百分比
- 生产月度预算上限为 500 USD
- 测试和开发月度预算上限各为 100 USD
- 总月度预算上限为 700 USD

真实环境是否已经部署、权限是否已经授予、告警是否已经到达、审计日志是否已经投递、恢复演练是否已经通过以及实际成本是否符合预算，必须由真实运行证据确认。
