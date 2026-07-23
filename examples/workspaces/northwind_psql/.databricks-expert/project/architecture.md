<!--
文件用途：记录项目已确认的 AWS 与 Databricks 架构约束，回答数据如何进入平台、如何形成可重放的当前状态，以及如何分层发布认证数据产品。
维护责任：由用户手动维护并确认。Agent 可以读取、引用、检查一致性和指出冲突，只能在本文约束内生成架构、配置和代码提案，不得自行改变已确认决定。
事实边界：源表、字段、数据类型、主键、外键和可空性只以 source-schema/northwind-schema.sql 为准。平台架构、运行参数、SLA、治理和恢复策略以已确认的项目需求文件为准。业务指标和数据处置口径以已确认业务与数据规则文件为准。
优先关系：源结构事实遵循 Northwind SQL 文件。平台设计与运行约束遵循已确认项目需求。业务口径遵循已确认业务与数据规则。文件之间出现冲突时必须先完成文档变更和人工确认，禁止由 Agent 自行选择或合并冲突口径。
内容边界：可以记录 RDS、DMS、S3、Unity Catalog、Auto Loader、Bronze、Silver、Gold、Ops、调度、重跑、补数、恢复和部署运行变量。不得写入真实凭据、密钥、令牌、账户编号、资源 ARN、端点、Workspace 编号或未经证实的部署状态。
当前状态：本文形成已确认架构基线，尚未被 project.yml 注册，也不代表任何 AWS 或 Databricks 资源已经创建、运行或验证。接入 Workspace Registry 必须作为独立受控变更执行并保留记录。
-->

# 项目架构与摄取约束

## 文档定位

本文定义 Northwind 销售分析项目从 Amazon RDS for PostgreSQL 到 AWS Databricks 的标准数据路径、资源边界、摄取行为、分层职责、调度方式和恢复顺序。

本文适用于 `dev`、`test` 和 `prod` 三个环境。后续 Terraform、Databricks Asset Bundles、Lakeflow Pipeline、Lakeflow Job、Notebook、SQL 和运维 Runbook 必须遵守本文。

本文只定义应采用的设计和约束。真实部署状态必须由目标环境中的资源清单、运行日志、质量结果、对账结果和发布记录证明。

## 当前架构决定

### 基准数据链路

项目基准链路固定为：

`Amazon RDS for PostgreSQL → AWS DMS Serverless → Amazon S3 Parquet → Unity Catalog External Volume → Auto Loader → Bronze Delta → Silver Delta → Gold Delta → Databricks SQL`

`ops` Schema 与上述链路并行承载运行元数据、质量结果、隔离记录、对账结果、Schema 漂移事件和发布水位。

架构采用事件驱动增量摄取和触发式计算。生产环境持续运行 DMS CDC，Databricks 计算在有文件到达或日终认证时启动，处理当前可用数据后停止。生产环境禁止为该项目维持空闲的持续计算集群。

### 区域、环境和时间

| 项目 | 已确认值 |
|---|---|
| 设计基线日期 | `2026-07-22` |
| AWS 区域 | `ap-northeast-1` |
| 调度时区 | `Asia/Tokyo` |
| 运行审计时间 | UTC |
| 源日期类型 | 保持 `DATE` |
| 源日期时区处理 | 不进行时区换算 |
| 环境 | `dev`、`test`、`prod` |
| 项目标识 | `northwind-sales` |
| 初始数据代际 | `v1` |

RDS、DMS、S3 和 Databricks Workspace 必须位于 `ap-northeast-1`。源 RDS 位于其他区域时，生产发布门禁失败，区域决定必须先通过正式变更控制修改。

每个环境使用独立 AWS 账户、独立 Databricks Workspace、独立 Catalog、独立 S3 Bucket、独立 KMS Key、独立运行身份和独立告警目标。

三个 Workspace 位于同一 Databricks Account，并绑定同一个东京区域 Unity Catalog Metastore。每个环境 Catalog 只绑定对应 Workspace，禁止跨环境读取和写入。

生产环境连接生产 RDS。开发和测试环境只能连接隔离的非生产 RDS 或经过批准的脱敏副本。

### Unity Catalog 组织

Unity Catalog Metastore 名称固定为 `northwind-tokyo-metastore`。

| 环境 | Catalog | Workspace Binding |
|---|---|---|
| 开发 | `northwind_dev` | 只绑定开发 Workspace |
| 测试 | `northwind_test` | 只绑定测试 Workspace |
| 生产 | `northwind_prod` | 只绑定生产 Workspace |

每个 Catalog 固定包含以下 Schema：

| Schema | 职责 |
|---|---|
| `landing` | 暴露 DMS S3 落地路径的 External Volume |
| `bronze` | 保存追加式原始 Full Load 与 CDC 事件 |
| `silver` | 保存按源主键合并后的源表当前状态 |
| `gold` | 发布五类认证数据产品 |
| `ops` | 保存质量、隔离、对账、运行、漂移和发布元数据 |

`bronze`、`silver`、`gold` 和 `ops` 中的表全部使用 Unity Catalog Managed Delta Table。DMS Parquet 文件不得注册为外部表。

Catalog 与 Schema Owner 固定为 `grp_northwind_platform`。Gold 表 Owner 固定为 `grp_northwind_product_owners`。生产 Catalog 禁止绑定到开发或测试 Workspace。

### 计算与部署形态

| 工作负载 | 已确认计算方式 |
|---|---|
| Bronze 与 Silver | Serverless Lakeflow Declarative Pipeline |
| Gold 刷新与质量任务 | Serverless Jobs |
| BI 与交互查询 | Serverless SQL Warehouse |
| 开发探索 | Serverless 或受策略约束的标准访问计算 |

生产 SQL Warehouse 名称固定为 `northwind-sales-prod-bi`，初始大小为 `2X-Small`，最小和最大集群数均为 1，空闲 10 分钟自动停止，Channel 固定为 Standard。

项目禁止使用 Preview、Beta、实验性或私有预览能力。

AWS 网络、IAM、KMS、S3、DMS 和告警资源使用 Terraform 管理。Databricks Metastore 绑定、Catalog、Schema、Storage Credential、External Location、Volume、权限和计算策略使用 Databricks Terraform Provider 管理。Pipeline、Job、Notebook、SQL 和配置使用 Databricks Asset Bundles 发布。

所有变更先进入开发环境，再进入测试环境，最后通过生产发布门禁进入生产环境。生产部署身份固定为 `sp_northwind_deploy_<environment>`，生产运行身份固定为 `sp_northwind_pipeline_<environment>`。生产 Job 和 Pipeline 必须由运行 Service Principal 执行，禁止由个人用户身份运行。Agent 只生成提案和评审材料，不执行部署。

## 源摄取范围

### 源事实基线

源数据库是 Amazon RDS for PostgreSQL 上的 Northwind 数据库，源 Schema 固定为 `public`。源结构唯一事实文件为 `source-schema/northwind-schema.sql`。

当前源结构包含 14 张表、92 个字段、14 个主键和 13 个外键。源文件没有视图、函数、存储过程、触发器、序列和显式普通索引。

Northwind 样例数据只用于结构映射、对账和非生产验收。样例数据不得用于推断生产规模、峰值、增长率、吞吐或成本。

### 精确表清单

DMS 使用精确表清单，禁止使用 Schema 通配符自动纳入新表。

纳入以下 14 张 `public` 表：

- `categories`
- `customer_customer_demo`
- `customer_demographics`
- `customers`
- `employees`
- `employee_territories`
- `order_details`
- `orders`
- `products`
- `region`
- `shippers`
- `suppliers`
- `territories`
- `us_states`

任何新增表必须先更新源 SQL 文件、项目需求、本文、DMS 映射、Databricks 显式 Schema、质量规则、权限和发布计划。

### 字段最小化

DMS 只摄取以下 62 个字段。未列出的 30 个字段在 DMS 表映射中通过白名单排除，不得进入 S3 或 Databricks。

| 源表 | 摄取字段 |
|---|---|
| `categories` | `category_id`、`category_name`、`description` |
| `customer_customer_demo` | `customer_id`、`customer_type_id` |
| `customer_demographics` | `customer_type_id`、`customer_desc` |
| `customers` | `customer_id`、`company_name`、`city`、`region`、`country` |
| `employees` | `employee_id`、`last_name`、`first_name`、`title`、`hire_date`、`reports_to` |
| `employee_territories` | `employee_id`、`territory_id` |
| `order_details` | `order_id`、`product_id`、`unit_price`、`quantity`、`discount` |
| `orders` | `order_id`、`customer_id`、`employee_id`、`order_date`、`required_date`、`shipped_date`、`ship_via`、`freight`、`ship_city`、`ship_region`、`ship_country` |
| `products` | 全部 10 个源字段 |
| `region` | `region_id`、`region_description` |
| `shippers` | `shipper_id`、`company_name` |
| `suppliers` | `supplier_id`、`company_name`、`city`、`region`、`country` |
| `territories` | `territory_id`、`territory_description`、`region_id` |
| `us_states` | `state_id`、`state_name`、`state_abbr`、`state_region` |

明确排除以下字段：

| 源表 | 排除字段 |
|---|---|
| `categories` | `picture` |
| `customers` | `contact_name`、`contact_title`、`address`、`postal_code`、`phone`、`fax` |
| `employees` | `title_of_courtesy`、`birth_date`、`address`、`city`、`region`、`postal_code`、`country`、`home_phone`、`extension`、`photo`、`notes`、`photo_path` |
| `orders` | `ship_name`、`ship_address`、`ship_postal_code` |
| `shippers` | `phone` |
| `suppliers` | `contact_name`、`contact_title`、`address`、`postal_code`、`phone`、`fax`、`homepage` |

排除字段属于 Restricted 数据或与五类数据产品无关的二进制内容。任何排除字段进入 DMS Parquet、Bronze、Silver 或 Gold 都属于 Sev 1 安全事件。

保留的 `categories.description` 和 `customer_demographics.customer_desc` 是无长度上限文本，因此 DMS 使用 Full LOB。二进制字段已在源端映射中排除。

## 全量初始化与 CDC

### DMS 任务基线

| 项目 | 已确认值 |
|---|---|
| DMS 形态 | AWS DMS Serverless |
| 迁移模式 | Full load and CDC |
| 生产运行方式 | 持续 CDC |
| 非生产运行方式 | 按需启动，测试完成后停止 |
| 最小容量 | 1 DCU |
| 最大容量 | 16 DCU |
| Multi AZ | 启用 |
| 网络 | 私有子网，至少跨两个可用区 |
| 公网访问 | 禁止 |
| S3 网络访问 | S3 Gateway VPC Endpoint |
| Secrets Manager 网络访问 | Secrets Manager Interface VPC Endpoint |
| 源连接端口 | PostgreSQL 5432 |
| 源 TLS | `verify-full` |
| 凭证来源 | AWS Secrets Manager 专用 Secret |
| PostgreSQL 解码插件 | `test_decoding` |
| DDL 自动捕获 | 关闭 |
| CloudWatch 日志 | 启用 |
| 预迁移评估 | 首次部署和重大变更前强制执行 |
| LOB 模式 | Full LOB |
| LOB Chunk | 64 KB |
| LOB 截断处置 | 发现截断即失败 |

DMS Serverless 配置名称固定为 `northwind-sales-<environment>-replication`。

源端点名称固定为 `northwind-sales-<environment>-postgres-source`。

S3 目标端点名称固定为 `northwind-sales-<environment>-s3-target`。

### PostgreSQL CDC 前置条件

- RDS PostgreSQL 参数组设置 `rds.logical_replication=1`，并在受控维护窗口完成必要重启。
- DMS 数据库角色固定为 `dms_northwind_<environment>`。
- DMS 角色只获得 `public` Schema 使用权、14 张批准表的读取权、心跳 Schema 使用权和 DMS CDC 所需复制权限。
- 应用账号、个人账号和 RDS Master 账号不得作为长期 DMS 运行身份。
- 项目使用一个活动逻辑复制槽，并额外预留一个备用槽位。
- `max_replication_slots` 必须至少比其他已用槽位数量多两个。
- `max_wal_senders` 必须至少比其他已用发送进程数量多两个。
- `wal_sender_timeout` 使用 RDS 默认值 30 秒。
- WAL Heartbeat 频率固定为 5 分钟，Schema 固定为 `dms_heartbeat`。
- 持续监控复制槽磁盘使用量、WAL 保留量、DMS 延迟和 RDS 可用存储。
- 活动 CDC 期间禁止修改主键结构。
- 业务删除使用行级 DELETE，禁止依赖 TRUNCATE 表达业务删除。
- 源 DDL 变更必须先更新源文件及全部下游约束，再进入部署评审。

Northwind 的 14 张表都具有主键。更新和删除 CDC 使用现有主键识别记录。目标层完整保留源主键值，不生成替代源键。

### 启动门禁

生产 DMS 任务只能在以下条件全部满足后启动：

- 预迁移评估没有错误
- 警告项已有平台 Owner 的书面处置记录
- 源端点连接测试成功
- S3 目标端点连接测试成功
- VPC Endpoint 状态为 Available
- CloudWatch 日志可写
- Secrets Manager Secret 可由专用 Role 读取
- S3 Bucket 与 KMS Key Policy 通过最小权限检查
- Restricted 字段排除映射通过静态检查
- 当前数据代际已经登记且未被其他活动任务占用

满足启动门禁只表示具备启动条件，不代表任务已经运行或验证。

### 全量初始化

初始全量数据代际固定为 `v1`。全量初始化使用同一 DMS Serverless 配置执行 Full Load 加持续 CDC，不建立独立的长期全量任务。

全量初始化遵循以下顺序：

1. 创建并登记当前数据代际及整数顺序
2. 创建 DMS 精确表映射和字段白名单
3. 完成连接测试与预迁移评估
4. 启动 Full Load 加 CDC
5. 将 Full Load 文件写入各表根目录
6. 将并行产生的 CDC 文件写入 UTC 小时目录
7. 由 Auto Loader 读取当前代际中尚未处理的文件
8. 由 Bronze 保存所有 Full Load 和 CDC 事件
9. 由 Silver 按源主键和确定性顺序形成当前状态
10. 完成行数、主键、外键、操作类型、金额和 Restricted 字段对账
11. 验证 INSERT、UPDATE、DELETE 和删除后重插
12. 通过发布门禁后启用认证 Gold 发布

Full Load 文件之间和 Full Load 与 CDC 文件之间不得依赖对象名称顺序。跨表一致性通过源主键、外键宽限、数据质量和发布门禁保证。

Full Load 记录的 `_dms_operation` 固定为 `INSERT`。`_dms_transport_operation` 允许为空。`_dms_commit_ts` 使用任务启动时间，只用于平台排序和审计，不作为业务事件时间。

### CDC 元数据

每条落地记录标准化保留下列 DMS 元数据：

| 列名 | 来源 | 用途 |
|---|---|---|
| `_dms_transport_operation` | DMS S3 CDC 原生操作标识 | 传输层校验 |
| `_dms_operation` | `$AR_H_OPERATION` | 标准操作类型 |
| `_dms_commit_ts` | S3 端点 TimestampColumnName | 源提交时间或 Full Load 任务启动时间 |
| `_dms_change_seq` | `$AR_H_CHANGE_SEQ` | 任务级事件顺序 |
| `_dms_stream_position` | `$AR_H_STREAM_POSITION` | PostgreSQL 日志流位置 |
| `_dms_source_schema` | `$AR_M_SOURCE_SCHEMA` | 源 Schema |
| `_dms_source_table` | `$AR_M_SOURCE_TABLE_NAME` | 源表 |
| `_dataset_generation` | 部署参数 | 区分受控全量数据代际 |

DMS 和 Databricks 元数据只用于摄取审计、排序、去重、删除和恢复，不得替代 `order_date`、`required_date` 或 `shipped_date` 等业务日期。

### CDC 操作语义

CDC 记录的 `_dms_operation` 只能取 `INSERT`、`UPDATE` 或 `DELETE`。

CDC 记录的 `_dms_transport_operation` 只能取 `I`、`U` 或 `D`，并且必须与 `_dms_operation` 语义一致。

操作类型缺失、非法或相互矛盾时，记录进入隔离，受影响数据产品停止认证发布。

Bronze 保留 DELETE 事件。Silver 收到有效 DELETE 后移除对应源业务键的当前记录。Gold 在后续刷新中移除由该记录产生的当前认证结果。

删除父记录后产生的非空外键孤儿允许 30 分钟处理宽限。宽限结束后仍未恢复的记录进入隔离，并阻断受影响 Gold 数据产品发布。

### 确定性排序与幂等

同一源业务键的版本优先级按以下顺序判断：

1. `_dataset_generation_rank`
2. CDC 高于 Full Load
3. `_dms_change_seq`
4. `_dms_commit_ts`
5. `_dms_stream_position`
6. `_ingested_at_utc`
7. `_source_file`

`_dms_change_seq` 必须转换为 `DECIMAL 38,0` 后参与排序。无法转换的记录进入隔离。

重复文件、任务重试、乱序事件、删除和删除后重插必须得到确定且幂等的 Silver 当前状态。下游禁止依赖跨表事务顺序。

### 数据代际

常规暂停、恢复和重试继续使用当前数据代际。以下场景创建新数据代际：

- 重新执行 DMS Full Load
- 更换 DMS 任务且无法安全续接原复制槽
- 更换源数据库或源目录
- 当前代际发生不可修复的数据污染

数据代际名称从 `v1` 开始递增。`_dataset_generation_rank` 使用不可复用的正整数顺序。`v1` 对应 1，后续代际每次递增 1。

新代际必须从 Full Load 加 CDC 开始。完成全量对账、CDC 连续性验证和质量门禁后，才能原子切换 Silver 和 Gold 的认证引用。旧代际保持只读并按保留策略清理。

## S3 文件与目录约定

### Bucket 划分与命名

每个环境使用三只独立 Bucket。

| 用途 | 命名规则 |
|---|---|
| DMS 落地区 | `northwind-sales-dms-<environment>-<aws_account_id>-ap-northeast-1` |
| Unity Catalog 托管存储 | `northwind-sales-uc-<environment>-<aws_account_id>-ap-northeast-1` |
| 审计日志 | `northwind-sales-audit-<environment>-<aws_account_id>-ap-northeast-1` |

DMS 落地区与 Unity Catalog 托管存储禁止共用 Bucket。外部服务不得直接访问 Unity Catalog 托管存储路径。

### Bucket 安全

所有 Bucket 采用以下控制：

- 区域固定为 `ap-northeast-1`
- 启用全部四项 S3 Block Public Access
- 使用 Bucket owner enforced
- 禁用 ACL
- 默认使用项目专用 KMS 客户管理密钥加密
- Bucket Policy 拒绝非 TLS 请求
- Bucket Policy 拒绝未使用指定 KMS 密钥的写入
- Bucket Policy 拒绝未批准 IAM Role 的访问
- KMS 自动轮换启用
- 禁止个人 IAM User 直接访问
- 生产 Bucket 启用 CloudTrail 数据事件
- S3 Gateway VPC Endpoint Policy 只允许访问本项目 DMS 落地 Bucket

KMS Alias 固定为：

- `alias/northwind-sales-dms-<environment>`
- `alias/northwind-sales-uc-<environment>`
- `alias/northwind-sales-audit-<environment>`

### DMS S3 端点参数

| 参数 | 已确认值 |
|---|---|
| `DataFormat` | `parquet` |
| `ParquetVersion` | `parquet-2-0` |
| `EnableStatistics` | `true` |
| `ParquetTimestampInMillisecond` | `false` |
| `EncryptionMode` | `SSE_KMS` |
| `ServerSideEncryptionKmsKeyId` | 部署运行变量 `dms_kms_key_arn` |
| `ServiceAccessRoleArn` | 部署运行变量 `dms_s3_role_arn` |
| `GlueCatalogGeneration` | `false` |
| `PreserveTransactions` | `false` |
| `DatePartitionEnabled` | `true` |
| `DatePartitionSequence` | `YYYYMMDDHH` |
| `DatePartitionDelimiter` | `SLASH` |
| `DatePartitionTimezone` | `Etc/UTC` |
| `TimestampColumnName` | `_dms_commit_ts` |
| `UseTaskStartTimeForFullLoadTimestamp` | `true` |
| `CdcInsertsOnly` | `false` |
| `CdcInsertsAndUpdates` | `false` |
| `CdcMaxBatchInterval` | 300 秒 |
| `CdcMinFileSize` | 32000 KB |
| `MaxFileSize` | 131072 KB |
| `ExpectedBucketOwner` | 部署账户编号 |
| `BucketFolder` | `landing/northwind/<dataset_generation>` |

`PreserveTransactions` 固定为 `false`。Parquet 按表落文件，日期分区按 UTC 小时建立。下游只依赖每张表内的源主键、数据代际、变更序列、提交时间和日志位置完成确定性合并。

### 路径规范

DMS 落地根路径固定为：

`landing/northwind/<dataset_generation>`

每张表根路径固定为：

`landing/northwind/<dataset_generation>/public/<table>`

Full Load 文件直接位于表根路径。

CDC 文件位于以下 UTC 小时目录：

`landing/northwind/<dataset_generation>/public/<table>/<utc_year>/<utc_month>/<utc_day>/<utc_hour>`

DMS 生成的对象名称按传输系统输出处理，下游不得从文件名推断业务日期、源主键或操作顺序。

禁止在已经投入使用的数据代际内改变 Schema 名、表名、目录层级和日期分区格式。路径变化必须创建新数据代际。

### 文件不可变性与 Versioning

DMS 落地文件采用追加写入，不覆盖已有对象。发现同键覆盖行为时立即阻断任务并升级为 Sev 2。

| Bucket | Versioning 决策 |
|---|---|
| DMS 落地区 | 关闭，使用不可变对象名和数据代际实现重放隔离 |
| Unity Catalog 托管存储 | 关闭，由 Delta Lake 管理表版本与清理 |
| 审计日志 | 开启，并启用 S3 Object Lock Governance |

### 生命周期

| 数据区域 | 生命周期与保留 |
|---|---|
| DMS 落地文件 | 0 至 90 天使用 S3 Standard，91 至 365 天使用 S3 Glacier Flexible Retrieval，满 365 天删除 |
| Unity Catalog 托管数据 | 不使用 S3 Lifecycle 直接删除 Delta 文件 |
| Lakeflow 内部状态 | Pipeline 有效期内持续保留，禁止配置对象生命周期删除 |
| 审计日志 | 保留 400 天，期间 Object Lock Governance 生效，期满后删除 |

DMS 落地文件可能因 5 分钟刷新形成较小对象，因此不使用 Standard IA。Glacier 归档恢复用于受控补数、审计和灾难恢复，不纳入 4 小时常规 RTO。

## Auto Loader 摄取要求

### Storage Credential、External Location 与 Volume

| 对象 | 命名 | 权限 |
|---|---|---|
| DMS 落地 Storage Credential | `sc_northwind_landing_<environment>` | 只读 DMS 落地 Bucket |
| 托管存储 Storage Credential | `sc_northwind_managed_<environment>` | 读写对应环境 Unity Catalog 托管 Bucket |
| DMS 落地 External Location | `ext_northwind_dms_<environment>` | 指向当前环境 DMS 落地根路径 |
| 托管存储 External Location | `ext_northwind_uc_<environment>` | 只供 Catalog Managed Location 使用 |

DMS 落地 Credential 使用 `role-northwind-databricks-landing-read-<environment>`。托管存储 Credential 使用 `role-northwind-databricks-uc-managed-<environment>`。两个 Role 必须分离，禁止合并权限。

在 `landing` Schema 中为 14 张源表分别创建 External Volume，命名为 `landing_<table>`。每个 Volume 指向当前数据代际对应表根路径，并覆盖 Full Load 文件和下级 UTC 小时目录。

Auto Loader 通过 Volume 路径读取文件，禁止在 Pipeline 代码中直接使用裸 S3 URI。

### Managed File Events

Managed File Events 在 `ext_northwind_dms_<environment>` 上启用。

| 项目 | 已确认值 |
|---|---|
| Pipeline 名称 | `northwind-sales-<environment>-ingestion` |
| Pipeline 类型 | Lakeflow Declarative Pipeline |
| 计算形态 | Serverless |
| 数据目录 | Unity Catalog |
| Bronze Auto Loader Flow | 14 个，每张源表一个 |
| Silver AUTO CDC Flow | 14 个，每张源表一个 |
| Pipeline Event Log | 通过 `ops.pipeline_run_metrics` 发布受控视图 |

每个 Bronze Flow 使用以下固定要求：

| 项目 | 已确认值 |
|---|---|
| 文件格式 | Parquet |
| 文件发现 | Auto Loader Managed File Events |
| Managed File Events 参数 | `cloudFiles.useManagedFileEvents=true` |
| 源 Schema | 从源 SQL 文件生成的显式 Schema |
| Schema 演进 | Rescue |
| ANSI 模式 | 启用 |
| Pipeline 模式 | Triggered |
| 处理语义 | 处理当前可用文件后停止 |

项目为 14 张源表分别定义一个 Bronze Auto Loader Flow。每个 Flow 只读取对应 `landing_<table>` Volume，禁止一个 Flow 通过通配路径混合读取多个源表。

首次 Pipeline 更新处理当前数据代际中尚未处理的 Full Load 文件和已到达的 CDC 文件。后续更新只处理 Lakeflow 状态中尚未提交的文件。

### 显式 Schema 与漂移

Auto Loader 不推断业务 Schema。显式 Schema 必须从 `source-schema/northwind-schema.sql` 和批准的 62 字段白名单生成。

新字段、字段类型变化和无法解析的值进入 `_rescued_data`。`_rescued_data` 非空的记录不得进入认证 Gold。

Schema 漂移写入 `ops.schema_drift_events` 并触发告警。Pipeline 不自动把新字段提升为 Silver 或 Gold 认证字段。

批准源 Schema 变更后，必须同步更新以下对象：

- 源 SQL 文件
- 项目需求与业务规则
- 本文
- DMS 表映射和字段白名单
- Auto Loader 显式 Schema
- Silver 类型转换
- 数据质量规则
- 数据字典
- Unity Catalog 权限与标签
- 受影响 Gold 数据产品
- 对账和发布计划

破坏性 Schema 变化先创建新列或新表，经开发和测试双轨验证后切换。

### Checkpoint 与 Schema State

Lakeflow 按 Flow 自动管理 Pipeline Checkpoint 和 Auto Loader Schema State。

代码和配置不得手工指定以下位置：

- `checkpointLocation`
- `cloudFiles.schemaLocation`

禁止手工删除、移动、复制或编辑 Lakeflow Checkpoint 和 Auto Loader Schema State。状态异常时必须遵循受支持的 Pipeline 恢复流程，并先在非生产环境验证。

每张源表使用独立 Bronze Flow 状态。单表失败不得通过清空整个 Pipeline 状态规避。

### Bronze 摄取元数据

每条 Bronze 记录除摄取范围内的源字段和 DMS 元数据外，还必须保留以下 Databricks 元数据：

| 列名 | 用途 |
|---|---|
| `_ingested_at_utc` | Databricks 摄取时间 |
| `_source_file` | 源文件路径 |
| `_source_file_modification_time` | S3 文件修改时间 |
| `_pipeline_update_id` | Pipeline Update 标识 |
| `_dms_load_phase` | `FULL_LOAD` 或 `CDC` |
| `_dataset_generation_rank` | 数据代际的受控整数顺序 |
| `_rescued_data` | 未匹配显式 Schema 的字段和值 |

`_dms_load_phase` 在 `_dms_change_seq` 和 `_dms_stream_position` 都为空时标记为 `FULL_LOAD`，其他记录标记为 `CDC`。

`_ingested_at_utc` 和 `_source_file_modification_time` 只用于平台审计与排序，不得作为业务事件时间。

### 吞吐与文件处理

项目初始不显式设置 Auto Loader 单次文件数或字节数上限。真实生产规模未知，吞吐限制必须基于待处理文件、待处理字节、运行时长和成本指标评审后调整。

未显式设置吞吐上限是已确认的初始运行决定，不构成开放参数。任何调整都必须保持最大 30 分钟数据延迟和单次运行 60 分钟超时约束。

DMS 目标文件大小是传输层目标。由 300 秒时间阈值提前刷新的较小文件生成警告，不自动判定为数据失败。

## Bronze、Silver、Gold 分层原则

### 分层依赖

标准依赖顺序固定为：

`Landing Volume → Bronze Changes → Silver Current State → Gold Certified Products`

`ops` 接收各层运行、质量、隔离、对账、漂移和发布元数据。

Gold 禁止直接读取 Landing Parquet 或 Bronze 事件。Silver 禁止绕过 Bronze 直接读取 S3。分析用户禁止直接读取 Landing、Bronze 和 Silver。

### Landing 层

Landing 只通过 Unity Catalog External Volume 暴露 DMS S3 对象，不复制、不改写、不注册为外部表。

Landing 文件保持 DMS 原始落地内容和目录结构。任何重命名、移动、格式转换或覆盖都会破坏可重放性，必须禁止。

Landing Role 只获得读取 DMS 落地 Bucket 所需的最小权限。DMS Role 只获得写入落地 Bucket 所需的最小权限。

### Bronze 层

Bronze 表命名为 `bronze.<table>_changes`。

Bronze 使用 Unity Catalog Managed Delta Streaming Table，保持追加写入。Bronze 不覆盖源事件，不物理执行源 DELETE，不进行业务字段纠错。

Bronze 保存以下内容：

- 批准的源字段原值
- DMS 操作与排序元数据
- Databricks 文件与运行元数据
- 数据代际
- Full Load 与 CDC 阶段标识
- Schema 漂移救援数据

源值异常通过质量标识、隔离记录和对账结果呈现。Bronze 禁止静默裁剪折扣、修改州缩写、补造维度值或纠正文本拼写。

Bronze CDC 历史保留 400 天。Delta 删除文件保留期固定为 30 天，事务日志保留期固定为 400 天。任何 `VACUUM` 都不得使用短于 30 天的保留期。

### Silver 层

Silver 表使用源表原名，命名为 `silver.<table>`。

Silver 使用 Unity Catalog Managed Delta Streaming Table，通过 Lakeflow AUTO CDC 实现 SCD Type 1 当前状态。主键完全沿用源表主键和组合主键。

Silver 必须完成以下处理：

- 按数据代际和确定性排序键选择每个源业务键的最新事件
- 将有效 DELETE 应用于当前状态
- 保持重复文件和任务重试幂等
- 标准化源数据类型
- 保留可追溯的源标识符
- 标记和隔离关键质量异常
- 允许跨表 CDC 乱序产生最长 30 分钟外键宽限

Silver 只提供当前状态，不承诺源系统上线前的属性历史。源 Schema 没有有效期字段，项目不得构造无法验证的历史维度版本。

源外键允许为空时，Silver 保持空值。不得生成未知客户、未知员工、未知承运商、未知品类或未知供应商等伪造维度成员。

### 数据类型标准化

| 源类型或字段 | Silver 与 Gold 处理 |
|---|---|
| PostgreSQL `smallint` | `SMALLINT` 或业务计算中的 `INT` |
| PostgreSQL `integer` | `INT` |
| PostgreSQL `character varying` 和 `text` | `STRING` |
| PostgreSQL `date` | `DATE` |
| DMS 提交时间字符串 | 严格解析为 UTC `TIMESTAMP` |
| `order_details.unit_price` | `DECIMAL 18,4` |
| `products.unit_price` | `DECIMAL 18,4` |
| `orders.freight` | `DECIMAL 18,4` |
| `order_details.discount` | `DECIMAL 9,6` |
| 派生金额 | `DECIMAL 20,4` |
| `products.discontinued` | 零转换为 false，一转换为 true，其他值隔离 |

认证金额计算不得直接使用 FLOAT 或 DOUBLE。金额和折扣先转换为定点小数，再按照已确认业务规则完成计算和 `HALF_UP` 四位小数舍入。

### Gold 层

Gold 由 Serverless Jobs 从 Silver 当前状态构建，使用 Unity Catalog Managed Delta Table。

认证数据产品固定为：

| 数据产品 | 认证表 |
|---|---|
| 每日销售 | `gold.daily_sales` |
| 客户价值 | `gold.customer_value` |
| 商品与品类日销售 | `gold.product_category_sales_daily` |
| 商品库存观察快照 | `gold.product_inventory_snapshot` |
| 员工销售表现 | `gold.employee_sales_daily` |
| 配送表现 | `gold.shipping_order_performance` |

认证销售只统计 `orders.shipped_date` 非空且通过关键质量规则的订单与订单明细。销售归属日期固定为 `orders.shipped_date`。

Gold 计算必须遵循已确认业务与数据规则，包括以下边界：

- 销售金额使用 `order_details.unit_price`
- `products.unit_price` 只表示当前商品目录价格
- 运费只在订单粒度计算一次
- 商品、品类和员工销售不分摊运费
- 源金额统一标记为 `source_currency_amount`
- 不推断取消、付款、退货、退款或实际送达
- 配送产品只发布发货处理代理指标
- 当前名称和组织属性来自 Silver 当前状态

Gold 使用确定性覆盖受影响日期、业务键或快照，禁止无条件追加重复聚合。

每个数据产品记录 `candidate`、`certified` 或 `blocked` 发布状态。只有关键质量规则全部通过、增量对账成功且新鲜度未超过 30 分钟时，才能更新为 `certified`。

失败运行不得覆盖最近一次已认证水位和已认证快照。

### Ops 层

Ops Schema 至少发布以下受控对象：

| 对象 | 用途 |
|---|---|
| `ops.pipeline_run_metrics` | Pipeline Event Log 的受控运行视图 |
| `ops.job_runs` | 编排与日终 Job 运行记录 |
| `ops.publish_watermarks` | 各数据产品输入与认证发布水位 |
| `ops.data_quality_results` | 质量规则结果 |
| `ops.quarantine_records` | 隔离记录与可追溯元数据 |
| `ops.source_reconciliation` | Full Load 与增量对账结果 |
| `ops.schema_drift_events` | Schema 漂移和救援数据事件 |

Pipeline Event Log 原始数据只允许平台与工程组读取。Steward 和运维通过受控 Ops 对象使用运行指标。

Ops 中不得保存 Restricted 源值、真实凭据或明文连接信息。

### Delta 存储布局

初始设计不对 Managed Delta Table 设置静态分区。生产数据量未知，禁止依据 Northwind 样例数据确定分区策略。

表布局优化必须基于真实查询、文件统计、扫描范围、运行时长和成本证据，并通过性能与成本评审后实施。

## 调度、重跑与补数

### 事件驱动编排

编排 Job 名称固定为 `northwind-sales-<environment>-orchestration`。

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

File Arrival Trigger 监控 `ext_northwind_dms_<environment>` 当前数据代际根路径，递归覆盖 14 张源表目录。

Job 执行顺序固定为：

1. 启动 ingestion Pipeline 并处理当前可用文件
2. 执行关键数据质量检查
3. 刷新五类 Gold 数据产品
4. 执行指标对账和发布门禁
5. 更新 `ops.publish_watermarks` 和 `ops.job_runs`
6. 发送成功、失败、超时、积压和质量通知

任何步骤失败时停止后续发布。失败运行不得推进 Gold 认证水位。

### 日终认证

独立日终 Job 名称固定为 `northwind-sales-<environment>-daily-certification`。

| 项目 | 已确认值 |
|---|---|
| 运行时间 | 每日 01:30 `Asia/Tokyo` |
| 销售认证截止 | 前一日历日期 |
| 完成目标 | 02:00 `Asia/Tokyo` 前 |
| 标准重跑窗口 | 最近 90 天 |
| 超过 90 天重跑 | 产品 Owner 和平台 Owner 双重批准 |

日终 Job 即使没有新文件也必须执行，用于刷新客户价值快照、商品库存观察快照、配送开放订单天数、对账和认证状态。

`gold.daily_sales` 认证前一日历日期。

`gold.customer_value` 的 `snapshot_date` 使用前一日历日期。

`gold.product_inventory_snapshot` 的 `snapshot_date` 使用 Job 运行时的东京日历日期，`snapshot_observed_at_utc` 记录实际观察时间。

源日期都是 `DATE`。日终边界只控制发布范围，不改变 `order_date`、`required_date` 或 `shipped_date` 的源值。

### 发布幂等与水位

- 同一 Pipeline Update 只允许一个活动实例。
- Bronze 依赖 Lakeflow 托管状态保证文件增量处理。
- Silver 依赖 AUTO CDC 排序键和源主键保证事件幂等。
- Gold 确定性覆盖受影响日期、业务键或快照。
- 每次发布记录输入水位、输出水位、源文件数量、Bronze 行数、Silver 变更数、Gold 行数和质量状态。
- 失败、超时、质量阻断和对账失败不得推进认证水位。
- 源端 DELETE 目标在 15 分钟内从 Silver 当前状态和后续 Gold 刷新中移除。

正常 CDC 新鲜度从 `_dms_commit_ts` 到 Gold `last_refreshed_at_utc` 计算。P95 目标为 15 分钟，最大允许延迟为 30 分钟。Full Load 记录不参与正常 CDC 新鲜度统计。

### 重跑类型

重跑按影响范围分为以下类型：

| 类型 | 使用场景 | 约束 |
|---|---|---|
| 原运行重试 | 短暂平台故障或可恢复任务失败 | 使用原 Pipeline 状态和原数据代际 |
| 失败对象刷新 | 单个 Flow 或依赖对象失败 | 只刷新失败对象及依赖，禁止清空全局状态 |
| Gold 定向重算 | 业务字段更正或历史日期受影响 | 确定性覆盖受影响日期、业务键或快照 |
| 标准历史补数 | 最近 90 天内的迟到、更正或重算 | 使用在线 Landing、Bronze 或 Silver 数据 |
| 受控历史补数 | 超过 90 天的更正或归档恢复 | 需要产品 Owner 和平台 Owner 双重批准 |
| 受控 Full Refresh | Pipeline 状态不可恢复且当前代际文件完整 | 先验证源文件完整性和重放范围 |
| 新数据代际重建 | 当前代际不完整、污染或 DMS 无法续接 | 新建 Full Load 加 CDC，完成验证后原子切换 |

业务更正涉及 `shipped_date`、订单客户、订单员工、运费、订单明细商品、交易单价、数量或折扣时，必须重算受影响 Gold 结果。

`shipped_date` 从空值变为日期时，订单进入认证销售。`shipped_date` 从日期变为空值时，订单从认证销售移除。`shipped_date` 改为其他日期时，原日期和新日期都必须重算。

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

禁止手工删除、移动或编辑 Lakeflow Checkpoint 和 Auto Loader Schema State。禁止在未验证源文件完整性时执行 Full Refresh。

旧数据代际在切换后保持只读。旧代际的删除遵循 DMS 落地 365 天和 Bronze 400 天保留策略。

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

RPO 由 DMS 300 秒最大批次间隔、PostgreSQL 逻辑复制槽和 S3 不可变落地共同支撑。

RTO 适用于区域内常规故障和最近 90 天在线数据，不包括 Glacier 归档恢复和跨区域灾难。

跨区域灾难恢复不在当前项目范围。

### 运行监控

架构运行至少监控以下指标：

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
- Auto Loader 待处理文件数、待处理字节数和最老文件时间
- Pipeline 运行时长、失败次数和 Flow 状态
- Gold 新鲜度和认证水位
- 关键数据质量失败数
- `_rescued_data` 记录数
- Restricted 字段扫描结果
- AWS 与 Databricks 审计日志最后投递时间

DMS Source Latency 或 Target Latency 超过 10 分钟生成 Warning，超过 20 分钟生成 Critical。Gold 新鲜度超过 20 分钟生成 Warning，超过 30 分钟生成 Critical。

Pipeline 首次失败生成 Warning，三次自动重试后仍失败生成 Critical。单次运行超过 45 分钟生成 Warning，超过 60 分钟生成 Critical。

日终认证在 01:50 前未完成生成 Warning，在 02:00 前未完成生成 Critical。

AWS 告警通过 `northwind-data-<environment>-alerts` SNS Topic 投递。Databricks 告警通过 `northwind-data-<environment>-ops` System Destination 投递。两个渠道汇入统一平台值班事件流，真实通知目标编号从部署运行变量读取。

### 数据保留

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
| 审计日志 | 400 天 |

收到具有法律效力的数据删除指令时，安全 Owner 启动例外删除流程，识别并清理 DMS 落地区、Bronze、Silver、Gold、隔离区、导出副本和缓存，并保留不含被删除内容的执行审计记录。

## 已确认参数与部署运行变量

### 架构参数状态

本文件没有开放的架构参数。原有待确认项已经按已确认项目需求转化为固定决定或部署运行变量。

以下项目属于固定决定，未经变更控制不得调整：

- AWS 区域为 `ap-northeast-1`
- 调度时区为 `Asia/Tokyo`
- 运行审计时间为 UTC
- DMS 使用 Serverless Full Load 加 CDC
- DMS 最小容量为 1 DCU，最大容量为 16 DCU
- DMS 生产持续运行，非生产按需运行
- S3 目标格式为 Parquet 2.0
- CDC 最大批次间隔为 300 秒
- S3 日期分区使用 UTC 小时目录
- DMS 事务保留关闭
- Managed File Events 启用
- Auto Loader 使用显式 Schema 和 Rescue
- Lakeflow 自动管理 Checkpoint 与 Schema State
- Pipeline 使用 Triggered 模式
- 编排最小触发间隔为 5 分钟
- 单次运行超时为 60 分钟
- 标准补数窗口为 90 天
- 日终认证在每日 01:30 东京时间启动
- 日终认证在每日 02:00 东京时间前完成
- P95 新鲜度目标为 15 分钟
- 最大允许延迟为 30 分钟
- RPO 为 5 分钟
- RTO 为 4 小时

### 部署运行变量

以下值必须从目标环境或受控部署参数读取。它们没有待设计含义，也不得以真实值写入本文或代码仓库明文配置。

| 变量 | 获取规则 |
|---|---|
| `aws_account_id` | 从目标 AWS 账户身份读取 |
| `environment` | 只能取 `dev`、`test`、`prod` |
| `aws_region` | 固定为 `ap-northeast-1` |
| `dataset_generation` | 初始为 `v1`，受控全量重建时递增 |
| `rds_endpoint` | 从目标 RDS 资源清单读取 |
| `rds_database` | 从受控部署参数读取 |
| `rds_ca_certificate_arn` | 从 RDS 证书清单读取 |
| `dms_kms_key_arn` | 通过 DMS KMS Alias 解析 |
| `uc_kms_key_arn` | 通过 Unity Catalog KMS Alias 解析 |
| `audit_kms_key_arn` | 通过审计 KMS Alias 解析 |
| `dms_s3_role_arn` | 从目标环境 IAM Role 读取 |
| `dms_secret_role_arn` | 从目标环境 IAM Role 读取 |
| `databricks_landing_role_arn` | 从目标环境 IAM Role 读取 |
| `databricks_managed_storage_role_arn` | 从目标环境 IAM Role 读取 |
| `databricks_workspace_id` | 从目标 Workspace 读取 |
| `databricks_metastore_id` | 从东京区域 Unity Catalog Metastore 读取 |
| `notification_destination_id` | 从已批准的平台值班通知目标读取 |

真实凭据只允许存储在 AWS Secrets Manager 或受批准的 Databricks 认证机制中。代码、Notebook、日志、质量结果和文档不得输出凭据值。

### 初始自适应参数决定

以下项目使用已确认的自适应策略，不作为开放参数：

- Auto Loader 不显式设置单次文件数和字节数上限
- Managed Delta Table 不设置静态分区
- DMS 在 1 至 16 DCU 范围内扩缩
- SQL Warehouse 初始保持单个 `2X-Small` 集群
- 文件大小、表布局和查询优化只根据真实运行指标调整

任何调整必须通过变更控制，并同时评估 SLA、成本、重放能力、对账和权限影响。

## 质量门禁与架构验收

### Full Load 验收

Full Load 完成后必须验证：

- 14 张源表全部完成且没有失败表或挂起表
- 62 个摄取字段与字段白名单一致
- Restricted 排除字段扫描结果为零
- DMS 落地、Bronze 和 Silver 行数可对账
- Silver 主键和组合主键重复数为零
- 持久外键孤儿数为零
- 代表性表完成 INSERT、UPDATE、DELETE 和删除后重插测试
- 每张表至少验证一条 CDC 事件的操作、提交时间、变更序列和日志位置
- 认证金额按照定点小数规则独立重算一致
- 运费只在订单粒度累计一次
- 已发货订单范围与 `shipped_date` 非空规则一致

上述条目是必须执行的验收要求，不代表当前环境已经通过。

### 持续发布门禁

每次 Gold 发布必须满足：

- 关键数据质量规则全部通过
- 增量对账成功
- 新鲜度未超过 30 分钟
- `_rescued_data` 未进入认证结果
- Restricted 字段扫描结果为零
- 当前数据代际属于批准配置
- 输入水位不早于最近一次已认证输入水位
- 输出覆盖范围与本次变更影响范围一致

门禁失败时，受影响数据产品状态更新为 `blocked`，最近一次已认证结果保持可用。

## 变更控制与 Workspace Registry

以下变更必须同步更新源事实或项目文档，并经过人工评审：

- 源表、字段、类型、主键、外键或可空性变化
- DMS 表清单、字段白名单、元数据或任务模式变化
- S3 Bucket、路径层级、日期分区或数据代际规则变化
- Unity Catalog Metastore、Catalog、Schema、External Location 或 Volume 变化
- Auto Loader Schema、Managed File Events 或状态管理方式变化
- Bronze、Silver、Gold 或 Ops 职责变化
- 调度频率、重试、超时、补数窗口、RPO、RTO 或保留期变化
- 敏感字段分类、权限、掩码或审计方式变化

本文被 `project.yml` 注册前，必须完成以下检查：

1. 文件路径和文档类型符合 Workspace Registry 规范
2. 文件内容与源 SQL、已确认项目需求和已确认业务数据规则一致
3. 文档校验值已记录
4. Registry 条目只声明文档可用性，不声明基础设施已部署
5. 注册变更经过用户确认并保留版本记录

Agent 后续只能在本文约束内生成方案。任何需要偏离本文的实现必须先提出冲突和影响，完成文档变更并获得用户明确确认。
