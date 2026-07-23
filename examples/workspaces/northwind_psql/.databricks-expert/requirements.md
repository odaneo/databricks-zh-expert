<!--
文件用途：记录项目目标、范围、源事实、已确认的数据产品口径、平台设计决策、技术约束、治理规则、运行目标和验收标准，是 Agent 理解项目目标与边界的主要输入。
维护责任：由用户手动维护并确认。Agent 可以读取、引用、检查一致性和指出冲突，不得自行改变本文件中的源事实、项目决策或部署状态。
事实边界：源结构事实仅来自 source-schema/northwind-schema.sql；样例数据验收事实仅来自 Workspace 根目录下固定的 upstream/northwind.sql。平台架构、命名、指标、SLA、治理和运维参数属于用户在本文件中确认的项目决策，不代表相关资源已经部署或验证。
决策状态：本版本在 2026-07-22 建立设计基线，原有设计空项已经全部转化为已确认项目决策。AWS 账户编号、资源 ARN、真实端点、Workspace 编号、密钥标识和凭证属于部署运行变量，不得写入真实值。
内容边界：不得记录密钥、密码、令牌、真实连接字符串、自动生成代码或未经证实的部署状态。
-->

# 项目需求

## 文档定位

本文件定义 Northwind 销售分析项目的业务目标、源事实边界、目标架构、数据模型、指标口径、安全治理、运行目标、成本边界和验收标准。

本文件中的内容按以下四类解释：

| 类别 | 定义 |
|---|---|
| 源结构事实 | 直接来自 source-schema/northwind-schema.sql 的表、字段、数据类型、主键和外键 |
| 样例验收事实 | 从固定的 upstream/northwind.sql 独立计算出的样例行数、日期范围、异常特征和金额基线 |
| 已确认项目决策 | 用户确认采用的平台架构、命名规则、摄取方式、指标口径、治理规则、SLA 和运维参数 |
| 部署运行变量 | 从实际 AWS 账户和 Databricks 工作区读取的账户编号、ARN、端点、Workspace 编号和密钥标识 |
| 部署状态 | 资源是否已经创建、运行和验证，只能由真实环境证据确认 |

后续架构、代码、Notebook、工作流和基础设施定义必须遵守本文件。任何与本文件冲突的实现都需要先修改本文件并获得用户明确确认。

## 业务目标

以 Northwind PostgreSQL 源 Schema 为唯一源数据事实基础，在 AWS Databricks 上设计一套可评审、可实施、可治理且不由 Agent 自动执行的销售分析方案。

方案支持以下五类数据产品：

- 每日销售
- 客户价值
- 商品与品类表现
- 员工销售表现
- 配送表现

方案同时覆盖源数据摄取、CDC 合并、质量控制、指标计算、权限治理、血缘审计、运行监控、故障恢复和成本控制。

## 源系统与事实边界

源系统是部署在 Amazon RDS for PostgreSQL 上的 Northwind 数据库。源 Schema 固定为 `public`。

Agent 注册并读取的结构事实文件固定为 `source-schema/northwind-schema.sql`。Workspace 根目录下的 `upstream/northwind.sql` 是固定的上游审计与样例验收文件，不注册为 Agent 上下文，也不得发送给模型。

两份文件职责和校验值如下：

| 文件 | 用途 | 编码 | 行数 | 字节数 | SHA256 |
|---|---|---|---:|---:|---|
| `source-schema/northwind-schema.sql` | 从固定上游脚本确定性派生的结构 DDL | UTF-8 | 214 | 6617 | `9857e1eec3687b47e6b4c55a087f77d7a272ff1f991e97bb31271ea30e7c1f9a` |
| `upstream/northwind.sql` | 完整上游脚本、审计依据和非生产样例验收夹具 | UTF-8 | 3912 | 349810 | `0ee30c01ba282f7194f38bf7f99cd6be0470b7ee5f67d0f7ca41fb058d735e0c` |

两份文件不要求内容相同。结构事实文件必须能够从固定上游脚本确定性再生成，并在表、字段、数据类型、主键和外键上保持结构一致。项目可依赖的源结构仅来自注册结构事实文件；该文件未定义的字段、状态、视图、函数、存储过程、触发器、序列和业务规则不得被当成源结构事实。

### 源 Schema 总览

| 项目 | 源事实 |
|---|---:|
| 数据表 | 14 |
| 字段 | 92 |
| 主键 | 14 |
| 外键 | 13 |
| 固定上游样例初始化数据 | 3362 行 |
| 视图 | 0 |
| 函数 | 0 |
| 存储过程 | 0 |
| 触发器 | 0 |
| 序列 | 0 |
| 显式普通索引 | 0 |

固定上游脚本中的样例初始化数据只用于理解结构、测试映射和验证指标，不得用于推断生产数据规模、吞吐、增长率、SLA 或成本。

### 源表清单与样例行数

| 源表 | 业务用途 | 主键 | 样例行数 |
|---|---|---|---:|
| `categories` | 商品品类 | `category_id` | 8 |
| `customer_customer_demo` | 客户与客户类型关联 | `customer_id` 加 `customer_type_id` | 0 |
| `customer_demographics` | 客户类型 | `customer_type_id` | 0 |
| `customers` | 客户 | `customer_id` | 91 |
| `employees` | 员工与汇报关系 | `employee_id` | 9 |
| `employee_territories` | 员工与销售区域关联 | `employee_id` 加 `territory_id` | 49 |
| `order_details` | 订单商品明细 | `order_id` 加 `product_id` | 2155 |
| `orders` | 订单 | `order_id` | 830 |
| `products` | 商品与库存 | `product_id` | 77 |
| `region` | 大区 | `region_id` | 4 |
| `shippers` | 承运商 | `shipper_id` | 6 |
| `suppliers` | 供应商 | `supplier_id` | 29 |
| `territories` | 销售区域 | `territory_id` | 53 |
| `us_states` | 美国州字典 | `state_id` | 51 |

### 样例数据验收基线

以下数值直接来自固定的 `upstream/northwind.sql`，只用于非生产映射测试、对账测试和指标验收。该上游文件发生变化后必须重新生成基线。

| 项目 | 样例值 |
|---|---:|
| 订单编号范围 | 10248 至 11077 |
| 下单日期范围 | 1996-07-04 至 1998-05-06 |
| 已发货订单 | 809 |
| 未发货订单 | 21 |
| 晚于要求日期发货的订单 | 37 |
| 订单明细 | 2155 |
| 订单商品总数量 | 51317 |
| 停售商品 | 10 |

这 37 张订单只用于验证发货处理代理指标，不得解释为实际延迟送达订单。

### 核心源关系

| 关系 | 源事实 |
|---|---|
| 客户到订单 | `orders.customer_id` 引用 `customers.customer_id` |
| 员工到订单 | `orders.employee_id` 引用 `employees.employee_id` |
| 承运商到订单 | `orders.ship_via` 引用 `shippers.shipper_id` |
| 订单到订单明细 | `order_details.order_id` 引用 `orders.order_id` |
| 商品到订单明细 | `order_details.product_id` 引用 `products.product_id` |
| 品类到商品 | `products.category_id` 引用 `categories.category_id` |
| 供应商到商品 | `products.supplier_id` 引用 `suppliers.supplier_id` |
| 大区到销售区域 | `territories.region_id` 引用 `region.region_id` |
| 员工到销售区域 | 通过 `employee_territories` 形成多对多关系 |
| 客户到客户类型 | 通过 `customer_customer_demo` 形成多对多关系 |
| 员工到上级员工 | `employees.reports_to` 自关联 `employees.employee_id` |

### 影响设计的源事实

- `order_details.unit_price` 是订单明细中的交易价格。销售金额必须使用该字段。
- `products.unit_price` 表示商品当前价格，只能作为当前商品属性使用。
- `orders.freight` 位于订单粒度。订单明细聚合不得重复累计运费。
- 源 Schema 没有货币代码。金额统一标记为源货币金额，不得声明为美元或其他具体币种。
- 源 Schema 没有订单状态、取消状态、付款状态、退货状态和退款状态。
- 源 Schema 没有实际送达日期。配送产品只能衡量发货处理及时性。
- `orders.shipped_date` 可为空。它是判断订单是否进入认证销售口径的唯一可用源字段。
- `orders.order_date`、`required_date` 和 `shipped_date` 都是日期，没有时分秒和时区。
- 金额、运费和折扣使用 PostgreSQL `real`。目标层必须先转换为定点小数再计算。
- `products.discontinued` 使用整数，源 Schema 没有布尔检查约束。
- `employee_territories` 是员工到区域的多对多关系，`orders` 没有 `territory_id`。员工订单不得分摊到销售区域。
- `us_states` 没有被其他源表通过外键引用，不得用于认证数据产品的自动地址映射。
- `customer_demographics` 和 `customer_customer_demo` 在样例数据中为空，但仍属于正式摄取范围。
- `categories.picture` 和 `employees.photo` 是二进制字段，与五类分析目标无关。
- 样例数据中的 Iowa 缩写为 `IO`。目标层按源值保留并生成质量警告，不自动改写。

## 项目范围

项目范围包括以下内容：

- 维护源 Schema 事实清单和校验值
- 设计 RDS PostgreSQL 到 Databricks 的全量与 CDC 摄取
- 设计 Landing、Bronze、Silver、Gold 和 Ops 数据层
- 设计五类数据产品及其认证指标
- 设计数据质量、权限、血缘、审计、监控、告警和恢复机制
- 提供供人工评审的 SQL、Python、Notebook、Lakeflow Pipeline、Lakeflow Job 和基础设施代码提案
- 通过部署运行变量适配真实 AWS 账户和 Databricks 工作区

## 不在范围

以下事项不在 Agent 的执行范围内：

- 连接真实 Amazon RDS、AWS 账户或 Databricks 工作区
- 创建、修改或删除真实 AWS 和 Databricks 资源
- 读取或保存真实密钥、密码、令牌和连接字符串
- 自动执行 SQL、Python、Notebook、Pipeline、Job 或 DMS 任务
- 修改 Northwind 源 Schema 或源数据
- 将设计状态描述为已部署、已运行或已验证
- 使用 Preview、Beta、实验性或私有预览能力
- 建设跨区域灾难恢复环境
- 推断源 Schema 没有提供的货币、取消、付款、退货、退款和实际送达事实

## 已确认事项总览

原设计空项统一按以下决策执行：

| 类别 | 已确认决策 |
|---|---|
| DMS | AWS DMS Serverless，Full load and CDC，S3 Parquet，保留操作类型、提交时间、变更序列和日志位置 |
| S3 | 每个环境使用独立 DMS 落地 Bucket、Unity Catalog 托管存储 Bucket 和审计 Bucket |
| Databricks | 每个环境独立 Workspace 与 Catalog，共用东京区域 Metastore，通过 Workspace Binding 隔离 |
| 调度 | `Asia/Tokyo`，事件触发最小间隔 5 分钟，每日 01:30 执行认证 |
| SLA | P95 新鲜度 15 分钟，最大延迟 30 分钟，日终 02:00 前完成，RPO 5 分钟，RTO 4 小时 |
| 数据产品 | 由 `grp_northwind_product_owners` 负责，五类产品使用本文固定表名和口径 |
| 销售口径 | 只统计 `shipped_date` 非空订单，销售归属日期使用 `shipped_date` |
| 治理 | Restricted 字段在 DMS 层排除，Confidential 字段按用途发布并应用列掩码 |
| 运维 | AWS SNS 与 Databricks System Destination 汇入统一平台值班事件流 |
| 保留 | DMS 落地 365 天，Bronze 400 天，销售 Gold 7 年，审计 400 天 |
| 成本 | 月度治理预算上限为生产 500 USD，测试 100 USD，开发 100 USD |

账户编号、真实 ARN、端点、Workspace 编号、通知目标编号和密钥标识由部署过程从目标环境读取。它们属于运行变量，不属于开放设计项。

## 已确认目标架构

基准链路固定为：

`Amazon RDS for PostgreSQL → AWS DMS Serverless → Amazon S3 Parquet → Unity Catalog External Volume → Auto Loader → Bronze Delta → Silver Delta → Gold Delta → Databricks SQL`

架构采用事件驱动的增量摄取和触发式计算。生产环境不运行空闲的持续计算集群。

### 区域、环境和时间

| 项目 | 已确认值 |
|---|---|
| 设计基线日期 | `2026-07-22` |
| AWS 区域 | `ap-northeast-1` |
| 调度时区 | `Asia/Tokyo` |
| 运行审计时间 | UTC |
| 源日期处理 | 保持 DATE，不进行时区换算 |
| 环境 | `dev`、`test`、`prod` |
| 项目标识 | `northwind-sales` |
| 初始数据代际 | `v1` |

RDS、DMS、S3 和 Databricks Workspace 必须部署在 `ap-northeast-1`。源 RDS 位于其他区域时，生产发布门禁直接失败，必须先通过正式变更控制修改区域决策。

每个环境使用独立 AWS 账户和独立 Databricks Workspace。三个 Workspace 位于同一 Databricks Account，并绑定同一个东京区域 Unity Catalog Metastore。每个环境 Catalog 只绑定对应 Workspace，禁止跨环境读取和写入。

生产环境连接生产 RDS。开发和测试环境只能连接隔离的非生产 RDS 或经过批准的脱敏副本。

### 部署运行变量

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

真实值不得进入本文件或代码仓库中的明文配置。

## AWS DMS 设计决策

### 任务模式

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
| PostgreSQL 插件 | `test_decoding` |
| DDL 自动捕获 | 关闭 |
| CloudWatch 日志 | 启用 |
| 预迁移评估 | 首次部署和重大变更前强制执行 |
| LOB 模式 | Full LOB |
| LOB Chunk | 64 KB |
| LOB 截断处理 | 发现截断即失败 |

DMS Serverless 配置名称固定为 `northwind-sales-<environment>-replication`。源端点名称固定为 `northwind-sales-<environment>-postgres-source`。S3 目标端点名称固定为 `northwind-sales-<environment>-s3-target`。

生产任务只能在预迁移评估无错误、源端与目标端连接测试成功、VPC Endpoint 状态为 Available、CloudWatch 日志可写后启动。警告项必须由平台 Owner 留下书面处置记录。

### PostgreSQL CDC 前置条件

- RDS PostgreSQL 参数组设置 `rds.logical_replication=1`，并在受控维护窗口完成必要重启。
- DMS 数据库角色固定为 `dms_northwind_<environment>`。
- DMS 数据库角色只获得 `public` Schema 使用权、14 张批准表的读取权、心跳 Schema 使用权和 DMS CDC 所需复制权限。
- 应用账号、个人账号和 RDS Master 账号不得作为长期 DMS 运行身份。
- 需要提升权限的初始化对象由数据库平台管理员一次性创建，完成后撤销临时权限。
- 项目占用一个活动逻辑复制槽，并额外预留一个备用槽位。
- `max_replication_slots` 必须至少比其他已用槽位数量多两个。
- `max_wal_senders` 必须至少比其他已用发送进程数量多两个。
- `wal_sender_timeout` 使用 RDS 默认值 30 秒。
- 启用 WAL Heartbeat，频率固定为 5 分钟，Schema 固定为 `dms_heartbeat`。
- 持续监控复制槽磁盘使用量、WAL 保留量、任务延迟和 RDS 可用存储。
- 活动 CDC 期间禁止修改主键结构。
- 业务删除使用行级 DELETE，禁止依赖 TRUNCATE 表达业务删除。
- 已批准的源 DDL 变更必须先更新注册结构事实文件、DMS 映射、Databricks 显式 Schema、质量规则和发布计划。

Northwind 的 14 张源表全部具有主键。更新和删除 CDC 以现有主键为识别基础。源 Schema 没有序列，目标层完整保留源主键值。

### 表选择与字段最小化

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

DMS 只摄取下列 62 个字段。未列出的 30 个字段通过字段白名单排除。

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

保留的 `categories.description` 和 `customer_demographics.customer_desc` 为无长度上限文本，因此任务采用 Full LOB。二进制字段不进入落地区。

### DMS 元数据列

每条记录标准化为以下元数据：

| 列名 | 来源 | 用途 |
|---|---|---|
| `_dms_transport_operation` | DMS S3 CDC 原生操作标识 | 传输层校验，值为 I、U、D，Full Load 可为空 |
| `_dms_operation` | `$AR_H_OPERATION` | 标准操作类型，值为 INSERT、UPDATE、DELETE |
| `_dms_commit_ts` | S3 端点 `TimestampColumnName` | CDC 使用源提交时间，Full Load 使用任务启动时间 |
| `_dms_change_seq` | `$AR_H_CHANGE_SEQ` | 任务级事件顺序 |
| `_dms_stream_position` | `$AR_H_STREAM_POSITION` | PostgreSQL 日志流位置 |
| `_dms_source_schema` | `$AR_M_SOURCE_SCHEMA` | 源 Schema |
| `_dms_source_table` | `$AR_M_SOURCE_TABLE_NAME` | 源表 |
| `_dataset_generation` | 部署参数 | 区分受控全量数据代际 |

`_dms_commit_ts` 在 Bronze 中严格解析为 UTC Timestamp。解析失败的记录进入隔离区。

CDC 记录必须同时保留传输层操作标识和标准操作类型。两者不一致时阻断受影响表发布。Full Load 只要求 `_dms_operation` 为 INSERT，传输层操作标识允许为空。

### S3 目标端点参数

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
| `CdcMaxBatchInterval` | `300` 秒 |
| `CdcMinFileSize` | `32000` KB |
| `MaxFileSize` | `131072` KB |
| `ExpectedBucketOwner` | 部署账户编号 |
| `BucketFolder` | `landing/northwind/<dataset_generation>` |

Full Load 文件位于表级目录：

`landing/northwind/<dataset_generation>/public/<table>`

CDC 文件按 UTC 小时分区：

`landing/northwind/<dataset_generation>/public/<table>/<utc_year>/<utc_month>/<utc_day>/<utc_hour>`

`PreserveTransactions` 固定为 `false`。Parquet 与日期分区方案按表落文件，无法保留跨表原始事务顺序。下游只依赖每张表内的主键、数据代际、变更序列、提交时间和日志位置完成确定性合并。跨表外键一致性通过质量宽限和发布门禁控制。

### 数据代际

常规暂停、恢复和重试继续使用当前数据代际。只有以下场景创建新数据代际：

- 重新执行 DMS Full Load
- 更换 DMS 任务且无法安全续接原复制槽
- 更换源数据库或源目录
- 当前代际发生不可修复的数据污染

新代际必须从 DMS Full Load 加 CDC 开始，完成全量对账和 CDC 连续性验证后再切换 Silver。旧代际保持只读并按保留策略清理。

## Amazon S3 设计决策

### Bucket 命名

| 用途 | 命名规则 |
|---|---|
| DMS 落地区 | `northwind-sales-dms-<environment>-<aws_account_id>-ap-northeast-1` |
| Unity Catalog 托管存储 | `northwind-sales-uc-<environment>-<aws_account_id>-ap-northeast-1` |
| 审计日志 | `northwind-sales-audit-<environment>-<aws_account_id>-ap-northeast-1` |

每个环境使用三只独立 Bucket。DMS 落地区与 Unity Catalog 托管存储禁止共用 Bucket。外部服务不得直接访问 Unity Catalog 托管存储路径。

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
- 生产访问只授予专用 IAM Role 和 Unity Catalog Storage Credential
- 禁止个人 IAM User 直接访问
- 生产 Bucket 启用 CloudTrail 数据事件
- S3 Gateway VPC Endpoint Policy 只允许访问本项目 DMS 落地 Bucket

KMS Alias 固定为：

- `alias/northwind-sales-dms-<environment>`
- `alias/northwind-sales-uc-<environment>`
- `alias/northwind-sales-audit-<environment>`

### Bucket Versioning

| Bucket | 决策 |
|---|---|
| DMS 落地区 | 关闭 Versioning，使用不可变文件名和数据代际实现重放隔离 |
| Unity Catalog 托管存储 | 关闭 Versioning，由 Delta Lake 管理表版本和清理 |
| 审计日志 | 开启 Versioning，并启用 S3 Object Lock Governance |

DMS 只追加新对象，不覆盖现有落地文件。发现同键覆盖行为时立即阻断任务并升级为 Sev 2。

### 路径规范

DMS 落地根路径固定为：

`landing/northwind/<dataset_generation>`

各表根路径固定为：

`landing/northwind/<dataset_generation>/public/<table>`

禁止在已投入使用的数据代际内改变 Schema 名、表名、目录层级和日期分区格式。路径变更必须创建新数据代际。

### 生命周期

| 数据区域 | 生命周期 |
|---|---|
| DMS 落地文件 | 0 至 90 天使用 S3 Standard，91 至 365 天使用 S3 Glacier Flexible Retrieval，满 365 天删除 |
| Unity Catalog 托管数据 | 不使用 S3 Lifecycle 直接删除 Delta 文件，由 Databricks 表保留策略管理 |
| Databricks Pipeline 内部状态 | 禁止配置对象生命周期删除 |
| 审计日志 | 保留 400 天，期间 Object Lock Governance 生效，期满后删除 |

DMS 落地文件可能因 5 分钟刷新形成较小对象，因此不使用 Standard IA。归档对象恢复只用于受控补数、审计和灾难恢复，不纳入 4 小时常规 RTO。

## Databricks 组织与命名

### Unity Catalog Metastore 与环境隔离

Unity Catalog Metastore 名称固定为 `northwind-tokyo-metastore`，区域固定为 `ap-northeast-1`。

| 环境 | Workspace | Catalog | Catalog Binding |
|---|---|---|---|
| 开发 | 独立开发 Workspace | `northwind_dev` | 只绑定开发 Workspace |
| 测试 | 独立测试 Workspace | `northwind_test` | 只绑定测试 Workspace |
| 生产 | 独立生产 Workspace | `northwind_prod` | 只绑定生产 Workspace |

每个 Catalog 固定包含以下 Schema：

| Schema | 用途 |
|---|---|
| `landing` | DMS S3 文件的 External Volume |
| `bronze` | 追加式原始 CDC 事件 |
| `silver` | 清洗后的源表当前状态 |
| `gold` | 认证数据产品 |
| `ops` | 质量、隔离、对账、运行元数据和受控事件日志视图 |

Catalog 使用 Catalog 级托管存储。`bronze`、`silver`、`gold` 和 `ops` 中的表全部使用 Unity Catalog Managed Delta Table。禁止把 DMS 落地 Parquet 注册为外部表。

Catalog 与 Schema Owner 固定为 `grp_northwind_platform`。生产 Catalog 禁止绑定到其他环境 Workspace。

### Storage Credential、External Location 与 Volume

| 对象 | 命名 | 权限 |
|---|---|---|
| DMS 落地 Storage Credential | `sc_northwind_landing_<environment>` | 只读 DMS 落地 Bucket |
| 托管存储 Storage Credential | `sc_northwind_managed_<environment>` | 读写对应环境 Unity Catalog 托管 Bucket |
| DMS 落地 External Location | `ext_northwind_dms_<environment>` | 指向当前环境 DMS 落地根路径 |
| 托管存储 External Location | `ext_northwind_uc_<environment>` | 只供 Catalog Managed Location 使用 |

DMS 落地 Credential 使用 `role-northwind-databricks-landing-read-<environment>`。托管存储 Credential 使用 `role-northwind-databricks-uc-managed-<environment>`。两个 Role 独立，禁止合并权限。

在 `landing` Schema 中为 14 张源表分别创建 External Volume，命名为 `landing_<table>`。每个 Volume 指向当前数据代际对应表根路径，并覆盖 Full Load 文件和下级 UTC 小时分区。

Managed File Events 在 `ext_northwind_dms_<environment>` 上启用。Auto Loader 通过 Volume 路径读取，不直接使用裸 S3 URI。

### 部署方式

- AWS 网络、IAM、KMS、S3、DMS 和告警资源使用 Terraform 管理。
- Databricks Metastore 绑定、Catalog、Schema、Credential、External Location、Volume、权限和计算策略使用 Databricks Terraform Provider 管理。
- Pipeline、Job、Notebook、SQL 和配置使用 Databricks Asset Bundles 发布。
- 所有部署先进入开发环境，再进入测试环境，最后通过生产发布门禁进入生产环境。
- 生产部署使用 `sp_northwind_deploy_<environment>`。
- 生产运行使用 `sp_northwind_pipeline_<environment>`。
- Agent 只生成提案和评审材料，不执行部署。

## Databricks 摄取与分层

### Lakeflow Pipeline

| 项目 | 已确认值 |
|---|---|
| Pipeline 名称 | `northwind-sales-<environment>-ingestion` |
| Pipeline 类型 | Lakeflow Declarative Pipeline |
| 计算形态 | Serverless |
| 模式 | Triggered |
| 更新语义 | 处理当前可用数据后停止 |
| 数据目录 | Unity Catalog |
| 源发现 | Auto Loader Managed File Events |
| Auto Loader 参数 | `cloudFiles.useManagedFileEvents=true` |
| 源 Schema | 从源 SQL 文件生成的显式 Schema |
| Schema 演进 | Rescue |
| ANSI 模式 | 启用 |
| Pipeline Checkpoint | 由 Lakeflow 按 Flow 自动管理 |
| Auto Loader Schema State | 由 Lakeflow 自动管理 |
| Pipeline Event Log | 发布受控视图 `ops.pipeline_run_metrics` |

Pipeline 为 14 张源表分别定义一个 Bronze Auto Loader Flow 和一个 Silver AUTO CDC Flow。各 Flow 使用独立的 Lakeflow 内部 Checkpoint。代码和配置不得手工指定 `checkpointLocation` 或 `cloudFiles.schemaLocation`。

Pipeline Event Log 原始数据只允许平台和工程组读取。Steward 和运维通过 `ops.pipeline_run_metrics` 使用受控指标。

### Bronze 层

Bronze 表命名为 `bronze.<table>_changes`。

Bronze 使用 Unity Catalog Managed Delta Streaming Table，保持追加写入，不覆盖源记录，不物理执行源 DELETE。每条记录保留摄取范围内的源字段、DMS 元数据和以下 Databricks 元数据：

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

`_dataset_generation_rank` 由部署配置维护。`v1` 对应 1，后续代际每次递增 1。禁止复用旧代际编号。

Bronze 不执行业务字段纠错。源值异常只通过质量标识、隔离记录和对账结果呈现。

### Silver 层

Silver 表使用源表原名，命名为 `silver.<table>`。

Silver 使用 Unity Catalog Managed Delta Streaming Table，通过 Lakeflow AUTO CDC 实现 SCD Type 1 当前状态。主键完全沿用源表主键。`_dms_operation` 为 DELETE 时删除 Silver 当前记录。

每张表的确定性排序键按以下优先级从高到低比较：

1. `_dataset_generation_rank`
2. CDC 高于 Full Load
3. `_dms_change_seq`
4. `_dms_commit_ts`
5. `_dms_stream_position`
6. `_ingested_at_utc`
7. `_source_file`

`_dms_change_seq` 转换为 `DECIMAL 38,0` 后参与排序。空值使用该数据类型的最小排序值。提交时间和日志位置作为后续平局处理依据。

删除、删除后重插、重复文件、任务重试和同一主键的乱序事件必须保持幂等。Silver 不依赖跨表事务顺序。外键一致性由质量宽限和发布门禁控制。

Bronze 保留可审计事件历史。Silver 只提供当前状态，不承诺源系统上线前的属性历史。源 Schema 没有有效期字段，因此项目不构造伪造的历史维度版本。

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
| `products.discontinued` | 0 转换为 false，1 转换为 true，其他值隔离 |

所有认证金额先转换为定点小数，再进行乘法、折扣和汇总。目标层不得直接使用 FLOAT 或 DOUBLE 完成认证金额计算。

### Schema 演进

- Auto Loader 使用源 SQL 文件生成的显式 Schema。
- 新字段、字段类型变化和无法解析的值进入 `_rescued_data`。
- `_rescued_data` 非空的记录不得进入认证 Gold。
- 源 Schema 漂移写入 `ops.schema_drift_events` 并触发告警。
- Pipeline 不自动把新字段提升为 Silver 或 Gold 认证字段。
- 批准变更后必须更新注册结构事实文件、DMS 映射、显式 Schema、质量规则、数据字典、权限和受影响数据产品。
- 破坏性 Schema 变化先创建新列或新表，经双轨验证后切换。

### Delta 存储布局

初始设计不对 Managed Delta Table 设置静态分区。生产数据量未知，禁止依据 Northwind 样例数据虚构分区策略。表布局优化必须基于真实查询和文件统计，并通过性能与成本评审后实施。

## 数据产品与认证口径

所有认证销售指标只统计 `orders.shipped_date` 非空，并且通过关键数据质量规则的订单与订单明细。

该规则避免把尚未发货且无法判断取消状态的订单计入已实现销售。源 Schema 没有取消、付款、退货和退款字段，因此认证销售不对这些业务事件作额外推断。

### 通用销售口径

| 指标 | 已确认定义 |
|---|---|
| 销售归属日期 | `orders.shipped_date` |
| 发货确认条件 | `orders.shipped_date` 非空 |
| 行毛额 | `order_details.unit_price` 乘 `quantity` |
| 行折扣额 | 行毛额乘 `discount` |
| 行净销售额 | 行毛额减行折扣额 |
| 订单商品净销售额 | 同一订单行净销售额之和 |
| 运费 | `orders.freight`，空值按零计入金额并保留缺失标识 |
| 含运费订单总额 | 订单商品净销售额加运费 |
| 平均订单金额 | 商品净销售额除以已发货订单数，不含运费；已发货订单数为零时为 null |
| 数量 | `order_details.quantity` 之和 |
| 客户数 | 非空 `customer_id` 去重数 |
| 货币 | 标记为 `source_currency_amount` |

认证金额统一采用以下计算顺序：

1. 将订单明细交易单价转换为 `DECIMAL 18,4`
2. 将折扣转换为 `DECIMAL 9,6`
3. 将运费转换为 `DECIMAL 18,4`
4. 行毛额使用转换后的交易单价乘数量，并通过 Databricks `round` 按 `HALF_UP` 保留四位小数
5. 行折扣额使用已舍入行毛额乘已转换折扣，并通过 Databricks `round` 按 `HALF_UP` 保留四位小数
6. 行净销售额使用已舍入行毛额减已舍入行折扣额
7. 订单、日期、客户、商品、品类和员工金额从已舍入的行级金额求和
8. Gold 金额字段统一保留四位小数

按照以上规则，固定上游样例中 809 张已发货订单的验收值如下：

| 指标 | 样例验收值 |
|---|---:|
| 商品毛额 | 1327014.8300 |
| 折扣额 | 87159.2210 |
| 商品净销售额 | 1239855.6090 |
| 运费 | 63955.0200 |
| 含运费订单总额 | 1303810.6290 |

这些金额只用于固定上游样例的自动化验收，不得作为生产业务结果。

销售金额必须使用 `order_details.unit_price`。`products.unit_price` 只表示当前商品目录价格。

运费先在订单粒度计算，再汇总到日期和客户。商品、品类和员工销售表不分摊运费。

源日期只有 DATE。所有按日指标直接使用源日期，不推导小时、分钟或时区内日界线。

当 CDC 更正 `shipped_date`、订单明细价格、数量或折扣时，Gold 必须重算受影响销售日期。

### 每日销售数据产品

| 项目 | 已确认值 |
|---|---|
| 认证表 | `gold.daily_sales` |
| 粒度 | 每个 `sales_date` 一行 |
| Owner | `grp_northwind_product_owners` |
| 发布对象 | 产品 Owner、数据 Steward、授权分析师 |

认证字段至少包括：

- `sales_date`
- `shipped_order_count`
- `distinct_customer_count`
- `units_sold`
- `gross_merchandise_amount`
- `discount_amount`
- `net_merchandise_sales`
- `freight_amount`
- `order_total_including_freight`
- `average_net_order_value`
- `freight_missing_order_count`
- `last_refreshed_at_utc`

`sales_date` 直接取 `orders.shipped_date`。同一订单无论包含多少订单明细，订单数和运费都只计算一次。

### 客户价值数据产品

| 项目 | 已确认值 |
|---|---|
| 认证表 | `gold.customer_value` |
| 粒度 | 每个 `snapshot_date` 和 `customer_id` 一行 |
| Owner | `grp_northwind_product_owners` |
| 发布对象 | 产品 Owner、数据 Steward、授权分析师 |

认证字段至少包括：

- `snapshot_date`
- `customer_id`
- `customer_company_name`
- `customer_city`
- `customer_region`
- `customer_country`
- `shipped_order_count`
- `units_sold`
- `gross_merchandise_amount`
- `discount_amount`
- `net_merchandise_sales`
- `freight_amount`
- `freight_missing_order_count`
- `average_net_order_value`
- `first_sales_date`
- `last_sales_date`
- `recency_days`
- `distinct_product_count`
- `distinct_category_count`
- `last_refreshed_at_utc`

该表包含 `silver.customers` 中的全部当前客户。没有已发货订单的客户保留一行，金额和计数为零，平均商品净订单金额、首次销售日期、最近销售日期和最近购买间隔为空。

`first_sales_date` 和 `last_sales_date` 基于 `shipped_date`。`recency_days` 等于 `snapshot_date` 减 `last_sales_date`。

该产品表示截至快照日期的已观察历史价值，不提供预测客户终身价值。

### 商品与品类表现数据产品

该数据产品包含两张认证表。

| 表 | 粒度 | 用途 |
|---|---|---|
| `gold.product_category_sales_daily` | 每个 `sales_date` 和 `product_id` 一行 | 商品与品类日销售表现 |
| `gold.product_inventory_snapshot` | 每个 `snapshot_date` 和 `product_id` 一行 | 当前价格和库存观察快照 |

销售表至少包含：

- `sales_date`
- `product_id`
- `product_name`
- `category_id`
- `category_name`
- `supplier_id`
- `supplier_company_name`
- `order_count`
- `customer_count`
- `units_sold`
- `gross_merchandise_amount`
- `discount_amount`
- `net_merchandise_sales`
- `last_refreshed_at_utc`

库存快照至少包含：

- `snapshot_date`
- `snapshot_observed_at_utc`
- `product_id`
- `product_name`
- `category_id`
- `category_name`
- `supplier_id`
- `supplier_company_name`
- `quantity_per_unit`
- `current_list_unit_price`
- `units_in_stock`
- `units_on_order`
- `available_supply_units`
- `reorder_level`
- `reorder_flag`
- `discontinued_flag`
- `last_refreshed_at_utc`

`available_supply_units` 等于空值按零处理后的 `units_in_stock` 加 `units_on_order`。

`reorder_flag` 规则如下：

- 商品已停售时为 false
- 商品未停售且 `reorder_level` 非空，并且 `available_supply_units` 小于等于 `reorder_level` 时为 true
- 商品未停售且 `reorder_level` 非空，并且 `available_supply_units` 大于 `reorder_level` 时为 false
- `reorder_level` 为空时为 null

库存源表没有更新时间。快照只能表示 Pipeline 观察时点的当前状态，不得声明为源系统日终库存。

### 员工销售表现数据产品

| 项目 | 已确认值 |
|---|---|
| 认证表 | `gold.employee_sales_daily` |
| 粒度 | 每个 `sales_date` 和 `employee_id` 一行 |
| Owner | `grp_northwind_product_owners` |
| 发布对象 | 产品 Owner、数据 Steward、授权分析师 |

认证字段至少包括：

- `sales_date`
- `employee_id`
- `employee_name`
- `employee_title`
- `manager_employee_id`
- `shipped_order_count`
- `distinct_customer_count`
- `units_sold`
- `gross_merchandise_amount`
- `discount_amount`
- `net_merchandise_sales`
- `average_net_order_value`
- `last_refreshed_at_utc`

订单只按 `orders.employee_id` 归属员工。员工区域关系只作为当前员工属性，不用于订单区域分摊或业绩重复归属。

### 配送表现数据产品

| 项目 | 已确认值 |
|---|---|
| 认证表 | `gold.shipping_order_performance` |
| 粒度 | 每个 `order_id` 一行 |
| Owner | `grp_northwind_product_owners` |
| 发布对象 | 产品 Owner、数据 Steward、授权分析师 |

认证字段至少包括：

- `order_id`
- `order_date`
- `required_date`
- `shipped_date`
- `shipper_id`
- `shipper_company_name`
- `ship_city`
- `ship_region`
- `ship_country`
- `freight_amount`
- `is_shipped`
- `days_to_ship`
- `shipped_by_required_date_proxy_flag`
- `days_shipped_after_required_date`
- `open_order_days`
- `required_date_missing_flag`
- `freight_missing_flag`
- `last_refreshed_at_utc`

口径规则如下：

- `days_to_ship` 等于 `shipped_date` 减 `order_date`
- `shipped_by_required_date_proxy_flag` 只在 `shipped_date` 和 `required_date` 都非空时计算
- `shipped_by_required_date_proxy_flag` 在 `shipped_date` 小于等于 `required_date` 时为 true
- `days_shipped_after_required_date` 在发货晚于要求日期时记录正数，在按期或提前发货时为零
- 未发货订单的 `days_to_ship`、`shipped_by_required_date_proxy_flag` 和 `days_shipped_after_required_date` 为空
- 未发货订单的 `open_order_days` 等于快照日期减 `order_date`

源 Schema 没有实际送达日期。`required_date` 与 `shipped_date` 的比较只作为发货处理代理指标。该表不得发布准时送达率、运输时长或承运商最终配送绩效。

### 当前属性与历史归属

客户公司名、商品名、品类名、供应商名、员工姓名、员工职位、经理关系和承运商名都来自 Silver 当前状态。源 Schema 没有属性有效期，因此历史销售行在刷新时可能显示最新名称或最新组织关系。

所有认证表保留稳定源标识符作为归属依据。名称变化不得改变订单、客户、商品和员工的源标识归属。需要历史有效期还原时必须增加可验证的源数据。

## 数据质量规则

### 质量处理原则

质量规则分为关键失败和警告。关键失败阻断受影响 Gold 数据产品发布。警告允许 Pipeline 完成，但必须写入质量结果并在规定期限内由 Steward 处置。

任何质量规则都不得静默修改源值。标准化的类型转换、空白处理和布尔映射必须保留原值或可追溯元数据。

### 关键规则

以下规则失败时阻断受影响 Gold 数据产品发布：

- 所有源主键字段非空
- Silver 主键组合唯一
- 非空外键必须在 30 分钟宽限后引用有效父记录
- `order_details.quantity` 大于零
- `order_details.unit_price` 大于等于零
- `order_details.discount` 位于零到一之间
- 已发货订单至少包含一条通过质量检查的订单明细
- `orders.freight` 大于等于零或为空
- `orders.shipped_date` 与 `orders.order_date` 都非空时，`shipped_date` 不早于 `order_date`
- `orders.required_date` 与 `orders.order_date` 都非空时，`required_date` 不早于 `order_date`
- `products.units_in_stock`、`units_on_order` 和 `reorder_level` 大于等于零或为空
- `products.discontinued` 只能为零或一
- `_dms_operation` 只能为 `INSERT`、`UPDATE`、`DELETE`
- `_dms_transport_operation` 非空时只能为 `I`、`U`、`D`
- CDC 记录的两种操作标识必须语义一致
- Full Load 记录的 `_dms_operation` 必须为 `INSERT`
- `_dms_commit_ts` 必须可解析为 UTC Timestamp
- `_dms_change_seq` 非空时必须可转换为 `DECIMAL 38,0`
- `_dms_source_schema` 必须为 `public`
- `_dms_source_table` 必须属于批准的 14 张表
- `_dataset_generation` 和 `_dataset_generation_rank` 必须属于批准数据代际
- `_rescued_data` 在认证数据中必须为空
- Restricted 排除字段不得出现在 DMS Parquet、Bronze、Silver 或 Gold
- 金额字段必须完成定点小数转换且无溢出

DMS Parquet 按表落文件，跨表变更可能短暂乱序。非空外键孤儿记录允许 30 分钟处理宽限。超过宽限仍未恢复时转为关键失败并隔离。

### 警告规则

以下问题生成警告，不自动修改源值：

- 文本拼写、空白和格式异常
- `us_states` 中未被源外键引用的异常缩写
- `customer_demographics` 或 `customer_customer_demo` 没有记录
- 源日期、运费或库存字段的空值比例发生显著变化
- 当前商品价格与历史订单明细价格不同
- 当前名称或组织关系变化导致历史展示属性重述
- 员工或客户维度缺失导致未分配订单
- 单个运行出现 `_rescued_data`
- DMS CDC 文件小于目标文件尺寸并由时间阈值提前刷新

`us_states` 中 Iowa 缩写 `IO` 按源事实保留并标记警告。

### 对账

Full Load 完成后必须在受控验证窗口完成以下对账：

- 14 张源表的行数与 DMS 落地和 Silver 一致
- 62 个摄取字段与字段最小化清单一致
- 所有 Silver 主键重复数为零
- 所有持久外键孤儿数为零
- DMS 表统计无失败表和挂起表
- 代表性表完成 INSERT、UPDATE、DELETE 和删除后重插测试
- 每张表至少验证一个 CDC 事件的操作、提交时间、变更序列和日志位置
- 销售金额按定点小数规则重算后与独立查询一致
- 运费只在订单粒度累计一次
- 已发货订单数、销售日期和商品数量与独立源查询一致
- Restricted 排除字段扫描结果为零

持续 CDC 每日执行以下增量对账：

- DMS 已处理记录数与 Bronze 新增记录数按表比较
- Bronze 到 Silver 的插入、更新和删除数量可解释
- Gold 已发货订单数与 Silver 认证订单数一致
- Gold 净销售额与订单明细独立重算结果一致
- 最新成功水位不早于已发布 Gold 水位

对账结果写入 `ops.source_reconciliation`。质量结果写入 `ops.data_quality_results`。隔离记录写入 `ops.quarantine_records`。Schema 漂移写入 `ops.schema_drift_events`。

### 发布状态

每个 Gold 数据产品必须记录以下状态：

- `candidate`
- `certified`
- `blocked`

只有关键规则全部通过、增量对账成功、数据新鲜度未超过最大允许延迟时，状态才能更新为 `certified`。失败运行不得覆盖最近一次已认证水位和认证快照。

## 调度与运行

### 事件驱动运行

| 项目 | 已确认值 |
|---|---|
| 编排 Job | `northwind-sales-<environment>-orchestration` |
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

File Arrival Trigger 监控 `ext_northwind_dms_<environment>` 当前数据代际根路径，递归覆盖 14 张源表目录。Pipeline 内部的每张表 Flow 只读取对应 `landing_<table>` External Volume，并使用 Lakeflow 自动管理的独立状态。

Job 执行顺序固定为：

1. 启动 ingestion Pipeline 更新并处理所有当前可用文件
2. 执行关键数据质量检查
3. 刷新五类 Gold 数据产品
4. 执行指标对账和发布门禁
5. 更新 `ops.publish_watermarks` 和 `ops.job_runs`
6. 发送成功、失败、超时、积压和质量通知

任何步骤失败时停止后续发布。失败运行不得推进 Gold 认证水位。

### 每日认证

独立日终 Job 名称为 `northwind-sales-<environment>-daily-certification`。

| 项目 | 已确认值 |
|---|---|
| 运行时间 | 每日 01:30 `Asia/Tokyo` |
| 销售认证截止 | 前一日历日期 |
| 完成目标 | 02:00 `Asia/Tokyo` 前 |
| 标准重跑窗口 | 最近 90 天 |
| 超过 90 天重跑 | 产品 Owner 和平台 Owner 双重批准 |

日终运行即使没有新文件也必须执行，用于刷新客户价值快照、库存观察快照、配送开放订单天数、对账和认证状态。

`gold.daily_sales` 认证前一日历日期。`gold.customer_value` 的 `snapshot_date` 使用前一日历日期。`gold.product_inventory_snapshot` 的 `snapshot_date` 使用 Job 运行时的东京日历日期，`snapshot_observed_at_utc` 记录实际观察时间。

### 发布幂等性

- 同一 Pipeline Update 只允许一个活动实例。
- Bronze 依赖 Lakeflow Checkpoint 保证文件增量处理。
- Silver 依赖 AUTO CDC 排序键和源主键保证重复事件幂等。
- Gold 使用确定性覆盖受影响日期或受影响快照，禁止无条件追加重复聚合。
- 每次发布记录输入水位、输出水位、源文件数量、Bronze 行数、Silver 变更数、Gold 行数和质量状态。

## SLA 与恢复目标

| 指标 | 已确认目标 |
|---|---|
| 端到端数据新鲜度 P95 | 源提交后 15 分钟内进入 Gold |
| 最大允许延迟 | 30 分钟 |
| 日终认证完成 | 每日 02:00 `Asia/Tokyo` 前 |
| 月度数据产品可用性 | 99.5 百分比 |
| RPO | 5 分钟 |
| RTO | 4 小时 |
| 标准补数窗口 | 90 天 |

数据新鲜度从 CDC `_dms_commit_ts` 到 Gold `last_refreshed_at_utc` 计算。Full Load 记录不参与正常 CDC 新鲜度统计。

月度可用性按计划认证窗口中成功保持 `certified` 状态的分钟数除以计划服务分钟数计算。提前公告并获得产品 Owner 与平台 Owner 批准的维护窗口不计入计划服务分钟数。

RPO 由 DMS 5 分钟最大批次间隔、逻辑复制槽和 S3 不可变落地共同支撑。RTO 适用于区域内常规故障和最近 90 天在线数据，不包括 Glacier 归档恢复和跨区域灾难。

### 恢复策略

恢复顺序固定如下：

1. DMS 故障优先使用原任务和原 PostgreSQL 逻辑复制槽恢复
2. Pipeline 故障优先使用原 Lakeflow 内部 Checkpoint 重试失败 Flow
3. 使用 Lakeflow 支持的刷新失败表能力只重跑失败对象及其依赖
4. Checkpoint 损坏时先在非生产验证受影响 Flow 的支持性恢复操作
5. 源数据代际完整保留时，对受影响 Bronze 和依赖 Silver 执行受控 Full Refresh
6. 当前代际历史文件不完整或 DMS 无法安全续接时，创建新数据代际并执行 DMS Full Load 加 CDC
7. Silver 可从完整 Bronze 或新数据代际重建
8. Gold 可从 Silver 重建

禁止手工删除、移动或编辑 Lakeflow Checkpoint 和 Auto Loader Schema State。禁止在未验证源文件完整性时执行 Full Refresh。

创建新数据代际后，旧 Bronze 保持只读。新 Silver 结果必须完成全量行数、主键、外键、金额和 CDC 连续性对账，再通过原子切换更新认证引用。

跨区域灾难恢复不在当前项目范围。区域内恢复依赖 DMS Multi AZ、S3、Unity Catalog Managed Delta 和受控重建能力。

## 治理与安全

### 数据分类

| 分类 | 字段与数据 |
|---|---|
| Restricted | 源端联系人、电话、传真、街道地址、邮政编码、员工出生日期、家庭电话、员工备注、图片和图片路径、订单收货人和详细收货地址 |
| Confidential | 客户公司名、员工姓名、职位、入职日期和汇报关系、供应商公司名、承运商公司名、城市、地区和国家 |
| Internal | 订单、订单明细、商品、品类、库存、区域、标识符和聚合指标 |
| Public | 当前没有源字段或数据产品被归类为 Public |

Restricted 字段通过 DMS 字段最小化排除，不进入 S3 和 Databricks。任何 Restricted 字段进入落地区或 Databricks 都属于 Sev 1 安全事件。

### Unity Catalog Group

| Group | 职责 |
|---|---|
| `grp_northwind_platform` | AWS、Databricks、DMS、存储、网络和运行平台 Owner |
| `grp_northwind_engineering` | Pipeline、模型、测试和发布实现 |
| `grp_northwind_stewards` | 数据定义、质量、分类和访问评审 |
| `grp_northwind_analysts` | 使用授权 Gold 数据产品 |
| `grp_northwind_product_owners` | 指标口径、SLA、验收和业务发布 Owner |
| `grp_northwind_security` | 安全策略、审计和敏感数据授权 |

Group 在身份提供方中管理，通过账户级 SCIM 同步。禁止创建 Workspace Local Group。权限优先授予 Group，禁止向个人直接授予生产数据权限。

### 运行身份

| 平台 | 身份 | 用途 |
|---|---|---|
| PostgreSQL | `dms_northwind_<environment>` | DMS 对 14 张源表和逻辑复制的受控读取 |
| AWS IAM | `role-northwind-dms-s3-<environment>` | DMS 写入落地 Bucket 并使用 DMS KMS Key |
| AWS IAM | `role-northwind-dms-secret-<environment>` | DMS 读取指定 Secrets Manager Secret |
| AWS IAM | `role-northwind-databricks-landing-read-<environment>` | Databricks 只读 DMS 落地区 |
| AWS IAM | `role-northwind-databricks-uc-managed-<environment>` | Unity Catalog 读写对应环境托管存储 |
| Databricks | `sp_northwind_pipeline_<environment>` | Pipeline、Job、质量和 Gold 发布运行身份 |
| Databricks | `sp_northwind_deploy_<environment>` | 受控发布 Terraform 和 Asset Bundles |

生产 Job 和 Pipeline 必须由运行 Service Principal 执行，不得由个人用户身份运行。部署 Service Principal 不读取业务表。运行 Service Principal 不拥有基础设施管理权限。

Databricks 自动化使用 OAuth 机器到机器认证，不使用个人访问令牌。AWS 服务访问使用专用 IAM Role，不使用 IAM User。

### 分层权限

| 层 | 访问规则 |
|---|---|
| DMS 落地区 | DMS 可写，Databricks Landing Role 可读，其他主体无访问 |
| Landing Volume | Pipeline Service Principal 可读，平台和工程可排障读取，其他主体无访问 |
| Bronze | Pipeline Service Principal 可写，平台、工程和 Steward 可读 |
| Silver | Pipeline Service Principal 可写，平台、工程和 Steward 可读，分析师无访问 |
| Gold | Pipeline Service Principal 可写，产品 Owner、Steward 和授权分析师可读 |
| Ops | Pipeline Service Principal 可写，平台和工程可读写，Steward 与安全组按职责只读 |

Catalog 和 Schema Owner 固定为 `grp_northwind_platform`。Gold 表 Owner 固定为 `grp_northwind_product_owners`。Pipeline Service Principal 通过最小写入授权更新 Gold，不获得 Owner 权限。

生产 Catalog 只绑定生产 Workspace。开发和测试主体不得获得生产 Catalog 的 `USE CATALOG`。

### 列级保护

- `customer_company_name` 对产品 Owner 和 Steward 显示原值，对普通分析师显示基于 `customer_id` 的稳定别名。
- `employee_name` 对产品 Owner 和 Steward 显示原值，对普通分析师显示基于 `employee_id` 的稳定别名。
- 列级保护统一使用 Unity Catalog 表级 Column Mask。
- Mask 函数由 `grp_northwind_security` 管理，Gold 表 Owner 负责绑定。
- 当前项目不使用 Dynamic View 承担字段脱敏。
- 当前项目不使用 ABAC Policy。
- 当前项目不实施行级过滤，因为源 Schema 没有可验证的组织访问边界字段。

稳定别名只包含对象类型和源标识符，不使用姓名、公司名、Secret 或可逆加密值。

### Governed Tags

所有 Catalog、Schema、Table 和关键 Column 使用以下标签：

- `data_domain=northwind_sales`
- `classification=restricted|confidential|internal`
- `owner_group=<group_name>`
- `retention_class=<retention_name>`
- `environment=dev|test|prod`
- `certification_status=raw|validated|certified|blocked`

Governed Tags 用于分类、发现、审计和质量检查，不作为当前项目的自动 ABAC 授权机制。

### 访问评审

- 生产访问每季度评审一次。
- 固定在一月、四月、七月和十月的前五个工作日完成。
- 离职、转岗和项目退出触发即时撤权。
- 紧急访问最长有效 8 小时，必须记录工单、批准人、用途和操作审计。
- 发现个人直授权、Workspace Local Group 或跨环境授权时立即撤销并记录整改。

### 血缘与审计

- Unity Catalog 血缘覆盖 Landing、Bronze、Silver、Gold、Pipeline 和 Job。
- Databricks 账户级审计日志以 JSON 投递到审计 Bucket。
- 生产审计证据以账户级审计日志投递为准。Audit System Table 只作为可用时的辅助查询来源。
- CloudTrail 记录 S3、KMS、Secrets Manager、IAM 和 DMS 管理事件。
- 生产 S3 Bucket 启用 CloudTrail 数据事件。
- Databricks 和 AWS 审计日志统一保留 400 天。
- 审计 Bucket 使用 Object Lock Governance 防止保留期内篡改。
- 审计日志读取只授予 `grp_northwind_security` 和受控审计身份。

### 密钥与凭证

- RDS 凭证存储在 AWS Secrets Manager 专用 Secret。
- Secret 包含 DMS 所需 Host、Port、Username 和 Password。
- Secrets Manager 凭证每 90 天轮换一次。
- KMS 客户管理密钥启用自动轮换。
- DMS、Landing、托管存储和审计使用不同 KMS Key。
- Databricks Service Principal 使用 OAuth 机器到机器认证。
- 代码、Notebook、配置、质量结果和日志不得输出凭证值。
- Secret 轮换后必须执行 DMS 端点连接测试和 Pipeline 只读连接测试。

### 安全验收

生产发布前必须由安全 Owner 验证：

- S3 Block Public Access 全部启用
- Bucket Policy 和 KMS Key Policy 符合最小权限
- VPC Endpoint Policy 只覆盖批准资源
- Restricted 字段扫描结果为零
- Column Mask 对授权与未授权主体结果正确
- 生产无个人直授权和 Workspace Local Group
- 审计日志能够持续投递并受 Object Lock 保护
- 紧急访问和季度评审流程可执行

## 运维与告警

### 告警渠道

| 渠道 | 已确认值 |
|---|---|
| AWS SNS Topic | `northwind-data-<environment>-alerts` |
| Databricks System Destination | `northwind-data-<environment>-ops` |
| 主要接收方 | 平台值班事件管理系统 |
| 业务升级接收方 | `grp_northwind_product_owners` |
| 安全升级接收方 | `grp_northwind_security` |
| 通知目标编号 | 部署运行变量 `notification_destination_id` |

AWS CloudWatch 通过 SNS 投递 DMS、RDS、S3、KMS 和成本告警。Databricks Job 与 Pipeline 通过 System Destination 投递失败、超时、积压、质量和新鲜度告警。两个渠道都必须进入同一平台值班事件流并生成可追踪事件编号。

### 告警阈值

| 监控项 | Warning | Critical |
|---|---|---|
| DMS CDC Source Latency | 超过 10 分钟 | 超过 20 分钟 |
| DMS CDC Target Latency | 超过 10 分钟 | 超过 20 分钟 |
| DMS Replication State | 状态异常持续 2 分钟 | 停止、失败或错误持续 5 分钟 |
| DMS Full Load 表状态 | 单表出现警告 | 失败表或挂起表数量大于零 |
| DMS DCU 使用 | 达到最大 DCU 持续 15 分钟 | 达到最大 DCU 持续 30 分钟并伴随延迟 |
| PostgreSQL 复制槽保留 WAL | 达到 RDS 分配存储的 10 百分比 | 达到 RDS 分配存储的 20 百分比 |
| RDS FreeStorageSpace | 低于 20 百分比 | 低于 10 百分比 |
| WAL Heartbeat | 10 分钟没有推进 | 20 分钟没有推进 |
| S3 或 KMS Access Denied | 单次事件 | 连续事件或影响生产写入 |
| Auto Loader 最老待处理文件 | 超过 10 分钟 | 超过 20 分钟 |
| Auto Loader 待处理字节 | 连续两次运行增长 | 连续四次运行增长并超过 SLA |
| Pipeline 运行 | 首次失败 | 3 次自动重试后仍失败 |
| Pipeline 运行时长 | 超过 45 分钟 | 超过 60 分钟 |
| Gold 数据新鲜度 | 超过 20 分钟 | 超过 30 分钟 |
| 关键数据质量失败数 | 不适用 | 大于零 |
| `_rescued_data` | 任一运行大于零 | 连续两次运行大于零或涉及认证字段 |
| Restricted 字段扫描 | 不适用 | 发现任一字段或值 |
| 日终认证 | 01:50 前未完成 | 02:00 前未完成 |
| 审计日志投递间隔 | 超过 15 分钟 | 超过 30 分钟 |
| 月度实际或预测成本 | 达到预算 80 百分比 | 达到预算 100 百分比 |

Critical 告警必须创建值班事件。Restricted 字段扫描命中、疑似数据泄露和不可恢复数据损坏直接按 Sev 1 处理。

### 必须监控的指标

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
- KMS 解密与加密拒绝
- Auto Loader 待处理文件数、待处理字节数和最老文件时间
- Pipeline 运行时长、失败次数和 Flow 状态
- Gold 新鲜度和认证水位
- 数据质量关键失败数
- `_rescued_data` 记录数
- Restricted 字段扫描结果
- SQL Warehouse 队列、运行时长和利用率
- AWS 与 Databricks 实际及预测成本
- AWS 与 Databricks 审计日志最后投递时间

### 故障等级

| 等级 | 条件 | 响应目标 |
|---|---|---|
| Sev 1 | 数据丢失、敏感数据泄露、Restricted 字段进入平台、不可恢复的数据损坏 | 15 分钟内确认，立即升级平台和安全 Owner |
| Sev 2 | 新鲜度超过 30 分钟、Job 重试后仍失败、DMS 停止、日终认证失败、审计中断 | 30 分钟内确认，4 小时内恢复 |
| Sev 3 | Schema 漂移、非关键质量警告、成本 Warning、单个非认证报表问题 | 下一个工作日处理 |

升级顺序固定为平台值班、平台 Owner、产品 Owner。涉及敏感数据、权限或审计时同时通知安全 Owner。

### Runbook 最低要求

每个 Critical 告警必须有对应 Runbook，至少包含：

- 影响判断
- 只读诊断步骤
- 停止发布条件
- 恢复步骤
- 回滚步骤
- 对账步骤
- Owner 与升级路径
- 证据留存位置

Runbook 不得要求手工删除 Lakeflow 内部状态、修改源数据或绕过 Unity Catalog 权限。

## 数据保留与删除

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

Delta 删除文件保留期固定为 30 天。Delta 事务日志保留期固定为 400 天。任何 `VACUUM` 都不得使用短于 30 天的保留期。

DMS 落地前 90 天保持 S3 Standard，支持标准重跑窗口和 4 小时常规 RTO。91 天后的归档恢复需要单独恢复窗口，不纳入常规 SLA。

源端 DELETE 事件在 15 分钟目标内从 Silver 当前状态和后续 Gold 刷新中移除。Bronze 和 DMS 落地区中的历史事件按受限保留策略保存，用于恢复、对账和审计。

收到具有法律效力的数据删除指令时，安全 Owner 启动例外删除流程，识别并清理 DMS 落地区、Bronze、Silver、Gold、隔离区、导出副本和缓存，并保留不含被删除内容的执行审计记录。

保留期、Lifecycle、Delta 属性或删除流程变更需要产品 Owner、平台 Owner、Steward 和安全 Owner 共同批准。

## 计算资源与成本

### 计算决策

| 工作负载 | 计算方式 |
|---|---|
| Bronze 与 Silver | Serverless Lakeflow Pipeline |
| Gold 刷新和质量任务 | Serverless Jobs |
| BI 和交互式查询 | Serverless SQL Warehouse |
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

禁止使用 Preview Channel。持续出现查询排队或磁盘溢写时，先优化数据模型、扫描范围和查询，再通过变更评审提升 Warehouse 大小或最大集群数。

DMS Serverless 最大容量为 16 DCU。达到最大 DCU 持续 15 分钟时先检查源事务、LOB、文件刷新和目标写入。提高最大容量需要成本评审。

### 成本预算

预算是项目治理上限，不代表真实生产成本预测或保证。

| 环境 | 月度预算上限 |
|---|---:|
| `prod` | 500 USD |
| `test` | 100 USD |
| `dev` | 100 USD |
| 合计 | 700 USD |

AWS Budgets 和 Databricks 账单使用量必须同时监控。预算告警阈值固定为实际和预测成本的 50、80、100 百分比。

- 达到 50 百分比时生成信息通知并检查月内进度。
- 达到 80 百分比时，平台 Owner 在两个工作日内完成成本分析和优化计划。
- 达到 100 百分比时，暂停非生产按需任务，生产继续满足 SLA，并由平台 Owner 和产品 Owner 批准预算或资源调整。

生产启用后的前 30 天作为真实成本基线期。基线报告至少拆分 RDS 增量负载、DMS DCU、S3 存储与请求、Databricks Pipeline、Jobs、SQL Warehouse、网络和日志成本。

30 天后只能通过变更控制调整预算、DMS 最大 DCU、SQL Warehouse 大小、触发频率和保留策略。不得根据 Northwind 样例数据预先声称预算充足。

所有 AWS 和 Databricks 资源使用以下成本标签：

- `project=northwind-sales`
- `environment=dev|test|prod`
- `owner=grp_northwind_platform`
- `cost_center=data-platform`
- `managed_by=iac`

无成本标签的资源不得进入生产发布。

## Owner 与审批责任

| 事项 | 最终责任 |
|---|---|
| 业务指标与数据产品验收 | `grp_northwind_product_owners` |
| 平台架构、SLA 和故障恢复 | `grp_northwind_platform` |
| Pipeline 和数据模型实现 | `grp_northwind_engineering` |
| 数据定义、质量和分类 | `grp_northwind_stewards` |
| 安全、审计和敏感访问 | `grp_northwind_security` |
| 日常分析使用 | `grp_northwind_analysts` |

审批规则如下：

- 指标口径变更需要产品 Owner 和 Steward 批准。
- 源字段纳入或排除变更需要产品 Owner、Steward 和安全 Owner 批准。
- SLA、成本预算和保留期变更需要产品 Owner 与平台 Owner 批准。
- 生产访问需要产品 Owner 和安全 Owner 批准。
- 源 Schema 变更需要工程、平台和 Steward 完成影响评估后由产品 Owner 批准。

## 发布门禁与验收标准

方案进入生产发布前必须满足以下条件：

- RDS、DMS、S3 和 Databricks Workspace 均位于 `ap-northeast-1`
- 开发、测试和生产 AWS 账户、Workspace、Catalog、Bucket、KMS Key 和运行身份完全隔离
- RDS 逻辑复制参数、复制槽容量、WAL Heartbeat 和 DMS 专用数据库角色已通过验证
- S3 Gateway VPC Endpoint 与 Secrets Manager Interface VPC Endpoint 状态为 Available
- DMS 预迁移评估无错误，所有警告均有平台 Owner 处置记录
- DMS 源端点和目标端点连接测试成功，TLS、Secret、KMS 和 Bucket Owner 校验通过
- 14 张源表均有显式 DMS 选择规则
- 每张源表均使用显式字段白名单
- 字段最小化规则与本文件一致
- 纳入摄取的 `text` 字段最大字节长度不超过已配置 LOB 上限
- DMS 全量与 CDC 测试覆盖插入、更新、删除和删除后重插
- DMS 元数据列完整，原生操作标识与 `_dms_operation` 一致
- Managed File Events、File Arrival Trigger 和 14 张 External Volume 均通过新增文件测试
- Lakeflow 为每张表维护独立托管状态，未手工配置 Checkpoint 或 Schema Location
- Bronze 保持追加和可重放
- Silver 主键唯一且删除处理正确
- 关键数据质量规则全部通过
- Full Load 行数对账全部通过
- 五类数据产品全部生成并通过样例指标对账
- 样例已发货订单数、商品毛额、折扣额、商品净销售额、运费和含运费总额与本文件验收基线一致
- 运费没有在订单明细粒度重复累计
- 认证销售只包含已发货订单
- 配送指标没有声明实际送达时间
- Catalog 和平台对象 Owner 为账户级 Group，Pipeline 使用专用 Service Principal 运行
- Catalog、Storage Credential 和 External Location 的 Workspace Binding 与环境一致
- Restricted 字段未进入 DMS 落地区和 Databricks
- Gold 列级保护通过授权和未授权用户测试
- 审计日志成功投递到受保护 S3 Bucket
- 告警能够到达平台值班系统
- RPO、RTO 和 90 天重跑演练通过
- AWS Budgets、资源标签和 Databricks 成本监控启用
- 所有生产组件使用正式发布能力和 Standard Channel
- Agent 未执行任何真实环境操作

## 变更控制

本文件中的源事实只能随 `source-schema/northwind-schema.sql` 的正式更新而变更。

已确认项目决策只能在用户明确指示后修改。任何修改都必须记录影响范围，至少覆盖源映射、DMS、S3、Databricks Schema、指标、质量、治理、SLA、成本和下游兼容性。

部署运行变量可以在不同环境中变化，但必须遵循本文件定义的命名、区域、安全和权限规则。

注册结构事实文件变更后必须重新计算其校验值和表字段统计，并复核全部结构依赖。固定上游脚本变更后必须验证来源版本与校验值、重新生成结构事实文件，并重新计算样例数据和认证金额验收基线。

## 设计依据

本项目的平台决策采用以下官方正式发布能力和生产建议：

- AWS Database Migration Service 私有网络与 VPC Endpoint
- AWS Database Migration Service 使用 Amazon S3 作为目标
- AWS Database Migration Service S3 Parquet 事务顺序与时间戳
- AWS Database Migration Service 使用 PostgreSQL 作为源
- AWS Database Migration Service Serverless
- Amazon S3 安全最佳实践
- Amazon S3 Object Ownership 与 Block Public Access
- Databricks Auto Loader 生产配置
- Databricks Auto Loader Managed File Events
- Databricks File Arrival Trigger
- Databricks Lakeflow Pipeline 托管 Checkpoint 与 Schema 状态
- Databricks Lakeflow AUTO CDC
- Databricks SQL `round` 的 `HALF_UP` 舍入规则
- Databricks Lakeflow Pipeline Run As 身份与权限
- Databricks Unity Catalog 最佳实践
- Databricks Workspace Catalog Binding
- Databricks Unity Catalog Column Mask
- Databricks Serverless Pipeline、Jobs 和 SQL Warehouse
- Databricks Job Notification
- Databricks Audit Log Delivery
- Databricks Billable Usage System Table
- Databricks Delta Lake 在 S3 上的限制
