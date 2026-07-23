<!--
文件用途：定义 Northwind 销售分析项目从源结构、摄取、CDC、Silver 当前状态到 Gold 数据产品需要满足的数据质量规则、严重等级、隔离方式、对账要求、告警阈值和人工处置责任。
维护责任：由用户手动维护并确认质量规则和阈值。Agent 可以读取、引用、检查一致性并生成检查实现草稿，不得擅自改变规则，也不得声称任何检查已经执行、通过或完成认证。
事实依据：源表、字段、数据类型、主键、外键和可空性只以 source-schema/northwind-schema.sql 为准。业务口径以已确认业务与数据规则文件为准。架构、摄取、SLA、治理、告警和保留要求以已确认项目需求及项目架构与摄取约束文件为准。逻辑产品粒度和交付边界以数据产品定义文件为准。
优先关系：源结构事实遵循 Northwind SQL 文件。业务口径遵循已确认业务与数据规则。平台与运行约束遵循项目需求和项目架构文件。文件之间出现冲突时必须停止受影响设计，提交冲突清单，并由用户完成文档变更和人工确认。
执行边界：本文定义必须执行的质量要求和验收证据，不代表真实 RDS、DMS、S3 或 Databricks 环境已经部署、运行、检查或通过。
内容边界：可以记录主键、外键、空值、重复、范围、日期一致性、CDC、Schema 漂移、隔离、对账、发布门禁、告警和人工处置要求。不得写入密钥、真实连接信息、生成代码、伪造检查结果或未经证实的部署状态。
-->

# 数据质量要求

## 文档定位

本文是 Northwind 销售分析项目的数据质量权威输入，规定数据从 DMS 落地到 Gold 认证发布必须满足的质量合同。

本文覆盖以下对象：

- 14 张已批准源表
- 62 个已批准摄取字段
- DMS 和 Databricks 处理元数据
- Landing、Bronze、Silver、Gold 和 Ops 各层
- 每日销售、客户价值、商品与品类表现、员工销售表现和配送表现
- Full Load、持续 CDC、重跑、补数和数据代际切换

本文只定义规则、阈值、处置和证据要求。真实检查状态只能由 `ops.data_quality_results`、`ops.source_reconciliation`、`ops.quarantine_records`、`ops.schema_drift_events`、Pipeline 运行记录和发布水位证明。

## 质量原则

### 事实优先

所有质量检查必须基于已批准源 Schema、已确认业务规则和已确认架构参数。

不得依据样例数据推断生产数据量、增长率、峰值、固定行数、固定增量或固定空值比例。

源 SQL 中没有定义的订单状态、取消、付款、退货、退款、货币代码和实际送达事实不得被纳入质量判断。

### 原值可追溯

Landing 和 Bronze 必须保留批准字段的原始值、源文件位置、数据代际、DMS 操作元数据和 Databricks 摄取元数据。

质量处理不得静默修改源值。以下行为均被禁止：

- 裁剪超出范围的折扣
- 将负数直接改为零
- 自动修正州缩写
- 自动改写文本拼写
- 生成虚假客户、员工、商品、品类、供应商或承运商
- 将 DELETE 改写为普通 UPDATE
- 使用当前商品价格覆盖订单明细交易价格
- 使用处理时间替代业务日期

### 分层阻断

质量结果分为两级：

| 级别 | 定义 | 发布影响 |
|---|---|---|
| 关键失败 | 破坏业务键、引用关系、核心指标、CDC 顺序、敏感数据边界或认证可追溯性的异常 | 隔离受影响记录并阻断受影响 Gold 数据产品认证 |
| 警告 | 不破坏核心事实，但需要监控、说明或人工治理的异常 | 允许处理继续，必须记录并在规定期限内处置 |

Gold 数据产品使用以下发布状态：

- `candidate`
- `certified`
- `blocked`

关键失败发生后，受影响产品更新为 `blocked`。失败运行不得覆盖最近一次已认证水位、认证快照或认证结果。

### 影响范围最小化

质量失败只阻断受影响表、依赖链和数据产品。没有依赖关系的产品可以继续发布，但必须保留清晰的影响分析和发布证据。

Restricted 字段命中、数据丢失、不可恢复数据损坏和敏感数据泄露属于全链路高危事件，必须立即停止受影响环境的发布并按 Sev 1 处置。

### 幂等与可重放

重复文件、任务重试、乱序事件、删除和删除后重插必须产生确定且幂等的 Silver 当前状态和 Gold 结果。

所有质量检查必须支持同一输入重复执行。重复执行不得生成重复隔离记录、重复质量结果或重复 Gold 聚合。

## 质量范围与责任

### 分层责任

| 数据层 | 质量职责 |
|---|---|
| Landing | 保持 DMS 文件不可变，验证目录、文件可读性、数据代际和批准表范围 |
| Bronze | 追加保存批准源值和平台元数据，验证 Schema、操作类型、解析能力和 Restricted 字段 |
| Silver | 按源业务键形成当前状态，执行主键、外键、范围、日期、类型和删除规则 |
| Gold | 验证业务粒度、认证销售范围、指标公式、维度归属、运费粒度和发布水位 |
| Ops | 保存质量结果、隔离记录、对账结果、漂移事件、运行证据和发布状态 |

Gold 禁止直接读取 Landing 或 Bronze。Silver 禁止绕过 Bronze 直接读取 S3。

### 责任主体

| 事项 | 最终责任 |
|---|---|
| 数据定义、质量规则和分类 | `grp_northwind_stewards` |
| 质量检查、Pipeline 和模型实现 | `grp_northwind_engineering` |
| 运行平台、告警、恢复和 SLA | `grp_northwind_platform` |
| 指标验收和业务发布 | `grp_northwind_product_owners` |
| Restricted 数据、审计和敏感访问 | `grp_northwind_security` |
| 授权分析使用 | `grp_northwind_analysts` |

关键质量规则变更需要 Steward 和产品 Owner 批准。涉及源字段纳入、排除或敏感分类时，还需要安全 Owner 批准。涉及 SLA、恢复、保留期或运行阈值时，还需要平台 Owner 批准。

## 源结构与摄取合同

### 源结构基线

| 项目 | 已确认事实 |
|---|---:|
| 源 Schema | `public` |
| 数据表 | 14 |
| 源字段 | 92 |
| 主键 | 14 |
| 外键 | 13 |
| 已批准摄取字段 | 62 |
| 已排除字段 | 30 |
| 注册结构事实文件 | `source-schema/northwind-schema.sql` |
| 注册结构文件行数 | 214 |
| 注册结构文件字节数 | 6617 |
| 注册结构文件 SHA256 | `9857e1eec3687b47e6b4c55a087f77d7a272ff1f991e97bb31271ea30e7c1f9a` |
| 固定上游样例文件 | `upstream/northwind.sql` |
| 固定上游文件行数 | 3912 |
| 固定上游文件字节数 | 349810 |
| 固定上游文件 SHA256 | `0ee30c01ba282f7194f38bf7f99cd6be0470b7ee5f67d0f7ca41fb058d735e0c` |

任一文件校验值变化时都必须停止自动纳入变化。注册结构事实文件变化后重新生成表字段统计、主外键清单、字段白名单、质量规则和影响分析；固定上游样例文件变化后还必须重新生成结构事实文件及全部样例验收基线。

### 已批准源表

DMS 只允许摄取以下 14 张表：

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

任何未列出的表进入 Landing 或 Bronze 均属于 Schema 漂移。生产环境禁止使用 Schema 通配符自动纳入新表。

### 字段白名单

DMS 只允许摄取以下字段：

| 源表 | 已批准字段 |
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

字段白名单必须在 DMS 表映射和 Databricks 显式 Schema 中保持一致。

### Restricted 字段零容忍

以下 30 个字段明确排除：

| 源表 | 排除字段 |
|---|---|
| `categories` | `picture` |
| `customers` | `contact_name`、`contact_title`、`address`、`postal_code`、`phone`、`fax` |
| `employees` | `title_of_courtesy`、`birth_date`、`address`、`city`、`region`、`postal_code`、`country`、`home_phone`、`extension`、`photo`、`notes`、`photo_path` |
| `orders` | `ship_name`、`ship_address`、`ship_postal_code` |
| `shippers` | `phone` |
| `suppliers` | `contact_name`、`contact_title`、`address`、`postal_code`、`phone`、`fax`、`homepage` |

任何排除字段名、排除字段值或可识别的排除字段载荷进入 DMS Parquet、Landing、Bronze、Silver 或 Gold，均按关键失败和 Sev 1 安全事件处理。

Restricted 字段扫描结果必须为零，才能通过 Full Load 验收和每次 Gold 发布门禁。

### Schema 漂移

以下变化均属于 Schema 漂移：

- 新增或删除源表
- 新增或删除源字段
- 字段数据类型变化
- 字段可空性变化
- 主键或外键变化
- 字段长度变化
- DMS 元数据缺失或新增
- 文件中出现未批准字段
- `_rescued_data` 出现内容

Schema 漂移统一记录到 `ops.schema_drift_events`。

单次运行出现 `_rescued_data` 时生成警告。连续两次运行出现 `_rescued_data`，或内容涉及认证字段、主键、外键、操作类型、排序字段或 Restricted 数据时，按关键失败处理。

任何 Schema 漂移在完成源文件更新、字段白名单评审、质量规则更新、权限评审和受控发布前，不得进入认证数据。


### 文本、LOB 与文件完整性

注册结构事实文件和固定上游样例文件编码均为 UTF-8。DMS 目标格式固定为 Parquet。

以下已批准字段使用无长度上限文本并采用 Full LOB 摄取：

- `categories.description`
- `customer_demographics.customer_desc`

以下情况按关键失败处理：

- Parquet 文件不可读取
- UTF-8 或 Parquet 解码失败
- LOB 被截断
- 已批准字段在下游被静默截短
- `character varying` 值超过源 DDL 声明长度
- 文件目录中的源表与 `_dms_source_table` 不一致
- 文件目录中的数据代际与 `_dataset_generation` 不一致

文本前后空白、大小写、拼写和格式异常生成警告。原值必须保留，不得通过静默清洗改变源事实。

## 主键完整性

### 主键清单

| 源表 | 主键 |
|---|---|
| `categories` | `category_id` |
| `customer_customer_demo` | `customer_id` 加 `customer_type_id` |
| `customer_demographics` | `customer_type_id` |
| `customers` | `customer_id` |
| `employees` | `employee_id` |
| `employee_territories` | `employee_id` 加 `territory_id` |
| `order_details` | `order_id` 加 `product_id` |
| `orders` | `order_id` |
| `products` | `product_id` |
| `region` | `region_id` |
| `shippers` | `shipper_id` |
| `suppliers` | `supplier_id` |
| `territories` | `territory_id` |
| `us_states` | `state_id` |

### 主键规则

所有主键字段必须满足以下要求：

- 值非空
- 组合主键中的每个组成字段都非空
- Silver 当前状态中每个主键或组合主键最多保留一行
- DELETE 事件能够完整识别目标业务键
- 数据代际切换后主键语义保持不变
- 不生成代理值替代缺失源主键
- 不使用名称、日期或文件位置替代源主键

Bronze 允许因重试、重复文件和 CDC 重放出现同一业务键的多个事件。Silver 必须按已确认版本顺序得到唯一当前状态。

同一业务键、同一版本排序值却具有不同业务载荷时，属于不可确定冲突，按关键失败处理。不得任意选择其中一条记录。

缺失主键的记录进入隔离区。受影响表及其下游产品停止认证发布。

### Gold 粒度唯一性

每个逻辑数据产品必须满足以下唯一粒度：

| 逻辑数据集 | 唯一粒度 |
|---|---|
| 每日销售 | 每个销售日期一条记录 |
| 客户价值 | 每个快照日期和客户一条记录 |
| 商品日销售表现 | 每个销售日期和商品一条记录 |
| 商品库存观察快照 | 每个快照日期和商品一条记录 |
| 员工销售表现 | 每个销售日期和员工一条记录 |
| 配送表现 | 每个订单一条当前记录 |

Gold 发现粒度重复时按关键失败处理。重跑和补数必须确定性覆盖受影响日期、快照或业务键，禁止无条件追加重复聚合。

## 外键引用完整性

### 外键清单

| 子表与字段 | 父表与字段 | 子字段可空 |
|---|---|---|
| `orders.customer_id` | `customers.customer_id` | 是 |
| `orders.employee_id` | `employees.employee_id` | 是 |
| `orders.ship_via` | `shippers.shipper_id` | 是 |
| `order_details.order_id` | `orders.order_id` | 否 |
| `order_details.product_id` | `products.product_id` | 否 |
| `products.category_id` | `categories.category_id` | 是 |
| `products.supplier_id` | `suppliers.supplier_id` | 是 |
| `territories.region_id` | `region.region_id` | 否 |
| `employee_territories.employee_id` | `employees.employee_id` | 否 |
| `employee_territories.territory_id` | `territories.territory_id` | 否 |
| `customer_customer_demo.customer_id` | `customers.customer_id` | 否 |
| `customer_customer_demo.customer_type_id` | `customer_demographics.customer_type_id` | 否 |
| `employees.reports_to` | `employees.employee_id` | 是 |

### 外键宽限

DMS Parquet 按表落文件，跨表变更可能短暂乱序。非空外键找不到父记录时，允许 30 分钟处理宽限。

宽限从子记录首次进入 Bronze 的 `_ingested_at_utc` 开始计算。宽限期间记录可以保留在受控候选状态，但不得进入依赖完整维度的认证结果。

30 分钟后仍无法找到父记录时，按关键失败处理：

- 子记录进入隔离
- 受影响 Silver 关系标记失败
- 受影响 Gold 产品更新为 `blocked`
- 最近一次已认证结果保持可用
- 生成 Critical 告警和可追踪事件编号

父记录后续到达时，可以在原数据代际内重新评估并重放受影响依赖。

### 合法空外键

允许为空的外键保持为空，不构成外键孤儿。

| 空值情况 | 质量与产品处置 |
|---|---|
| `orders.customer_id` 为空 | 订单保留在适用的总销售和商品结果中，不归属客户价值，客户去重数不计空值 |
| `orders.employee_id` 为空 | 订单保留在适用的其他销售结果中，不归属员工销售 |
| `orders.ship_via` 为空 | 配送记录保留，承运商标识和属性为空 |
| `products.category_id` 为空 | 商品记录保留，品类属性为空 |
| `products.supplier_id` 为空 | 商品记录保留，供应商属性为空 |
| `employees.reports_to` 为空 | 员工保留，可表示组织层级根节点 |

不得为合法空外键生成 Unknown、Unassigned、N A、零值标识符或人工代理成员。

### 特殊引用边界

`us_states` 没有被其他源表通过外键引用，不得用于认证地址的自动映射或自动修正。

`customer_demographics` 和 `customer_customer_demo` 在固定上游样例 SQL 中没有初始化记录。空表本身生成警告，不构成关键失败，也不得从其他字段推断客户类型。

员工与销售区域通过 `employee_territories` 形成多对多关系。`orders` 没有 `territory_id`，员工销售不得分摊到销售区域。

## 必填字段与空值

### 源端非空字段

以下字段在源 DDL 中定义为非空：

| 源表 | 非空字段 |
|---|---|
| `categories` | `category_id`、`category_name` |
| `customer_customer_demo` | `customer_id`、`customer_type_id` |
| `customer_demographics` | `customer_type_id` |
| `customers` | `customer_id`、`company_name` |
| `employees` | `employee_id`、`last_name`、`first_name` |
| `employee_territories` | `employee_id`、`territory_id` |
| `order_details` | `order_id`、`product_id`、`unit_price`、`quantity`、`discount` |
| `orders` | `order_id` |
| `products` | `product_id`、`product_name`、`discontinued` |
| `region` | `region_id`、`region_description` |
| `shippers` | `shipper_id`、`company_name` |
| `suppliers` | `supplier_id`、`company_name` |
| `territories` | `territory_id`、`territory_description`、`region_id` |
| `us_states` | `state_id` |

已批准字段中的源端非空值进入 Bronze 或 Silver 后变为空时，按关键失败处理。

### 可空值保留

源 DDL 允许为空的字段原则上保持为空。目标层不得通过默认文本、零值日期或人工编号掩盖缺失。

当前只允许以下指标级替代：

- `orders.freight` 为空时，在指定金额指标中按零计入，同时保留运费缺失标识
- `products.units_in_stock` 和 `products.units_on_order` 为空时，在可用供应数量计算中按零处理，同时保留缺失标识

替代只用于派生指标。Silver 中的原始空值必须保留。

### 产品相关空值

- 已发货订单的 `shipped_date` 必须非空，这是进入认证销售的条件。
- `required_date` 为空时，发货及时性代理指标保持为空。
- 未发货订单的 `days_to_ship`、`shipped_by_required_date_proxy_flag` 和 `days_shipped_after_required_date` 保持为空。
- 未发货订单的 `order_date` 为空时，`open_order_days` 保持为空。
- 当前名称为空时保留源标识符和空名称，不生成替代名称。
- 当前属性空值不得改变稳定源标识归属。


## 数据类型与解析完整性

### 源类型标准化

| 源类型或字段 | Silver 与 Gold 标准化 |
|---|---|
| PostgreSQL `smallint` | `SMALLINT` 或业务计算使用的 `INT` |
| PostgreSQL `integer` | `INT` |
| PostgreSQL `character varying` 和 `text` | `STRING` |
| PostgreSQL `date` | `DATE` |
| DMS 提交时间字符串 | UTC `TIMESTAMP` |
| `order_details.unit_price` | `DECIMAL 18,4` |
| `products.unit_price` | `DECIMAL 18,4` |
| `orders.freight` | `DECIMAL 18,4` |
| `order_details.discount` | `DECIMAL 9,6` |
| 派生金额 | `DECIMAL 20,4` |

### 解析规则

- 使用显式 Schema，禁止依赖自动推断形成认证字段类型。
- 非空源值解析失败时按关键失败处理。
- 可空源值只有源值本身为空时才能保持为空。
- 非空文本解析失败后不得静默转换为空值。
- 日期必须严格解析为 `DATE`。
- DMS 提交时间必须严格解析为 UTC Timestamp。
- 数值转换必须检测溢出、无穷值和非数值。
- `products.discontinued` 只允许零和一映射为布尔值。
- 解析失败的原始载荷和来源元数据必须进入隔离证据。
- `_rescued_data` 不得进入 Silver 认证状态或 Gold 产品。

类型标准化不得改变源业务键、日期语义或金额口径。

## 数量、单价、折扣与库存范围

### 订单明细范围

| 字段 | 合法范围 | 失败级别 |
|---|---|---|
| `order_details.quantity` | 大于零 | 关键失败 |
| `order_details.unit_price` | 大于等于零 | 关键失败 |
| `order_details.discount` | 大于等于零且小于等于一 | 关键失败 |

不为数量、交易单价或折扣虚构源 Schema 未定义的上限。

`discount` 等于零和等于一都属于合法边界。`unit_price` 等于零属于合法值，不得自动改写。

### 运费范围

`orders.freight` 大于等于零或为空。

运费小于零时按关键失败处理。运费为空时按零参与已确认金额指标，并保留缺失标识或缺失计数。

每张订单的运费只能累计一次。运费可以进入每日销售和客户价值，不得分摊到商品、品类或员工销售金额。

### 商品库存范围

以下字段大于等于零或为空：

- `products.units_in_stock`
- `products.units_on_order`
- `products.reorder_level`

负值按关键失败处理。空值按源值保留，只在已确认可用供应数量计算中使用零替代并保留缺失标识。

`products.discontinued` 只能取零或一。零转换为 false，一转换为 true。其他值进入隔离并按关键失败处理。

### 当前商品价格

`products.unit_price` 是当前商品目录属性，不得用于重算历史销售。

当前商品价格与 `order_details.unit_price` 不同属于正常业务现象。价格差异可以生成解释性警告，不构成订单销售质量失败。

## 金额计算与数值精度

### 定点小数转换

源金额和折扣使用 PostgreSQL `real`。Silver 和 Gold 必须先完成以下定点小数转换：

| 源字段或派生值 | 目标数值类型 |
|---|---|
| `order_details.unit_price` | `DECIMAL 18,4` |
| `products.unit_price` | `DECIMAL 18,4` |
| `orders.freight` | `DECIMAL 18,4` |
| `order_details.discount` | `DECIMAL 9,6` |
| 派生金额 | `DECIMAL 20,4` |

解析失败、精度丢失不可解释或数值溢出时按关键失败处理。

认证金额不得直接使用 FLOAT 或 DOUBLE 计算。

### 指标恒等式

订单行毛额等于交易单价乘商品数量。

订单行折扣金额等于订单行毛额乘折扣比例。

订单行净销售额等于订单行毛额减订单行折扣金额。

订单净销售额等于同一 `order_id` 下全部有效订单明细净销售额之和。

含运费订单总额等于订单净销售额加订单运费。

所有派生金额使用 `HALF_UP` 四位小数规则。对账必须使用相同转换顺序和舍入规则。

以下恒等式不成立时按关键失败处理：

- 毛额减折扣金额等于净销售额
- 订单明细净销售额之和等于订单净销售额
- 商品净销售额加订单粒度运费等于含运费订单总额
- 各产品按相同认证范围汇总后，公共净销售额保持一致

### 源货币边界

源 Schema 没有货币代码。所有金额只能标记为源系统金额。

不得将金额声明为美元、日元或其他具体币种，不进行汇率换算，也不混入外部汇率数据。

## 日期一致性

### 日期语义

| 字段 | 业务含义 |
|---|---|
| `orders.order_date` | 订单创建日期 |
| `orders.required_date` | 要求发货日期 |
| `orders.shipped_date` | 实际发货日期和认证销售归属日期 |
| `employees.hire_date` | 当前员工属性中的入职日期 |

源日期类型为 `DATE`，没有时分秒和时区。目标层保持 `DATE`，不得进行时区换算。

DMS `_dms_commit_ts` 和 Databricks 摄取时间属于平台审计时间，不得替代业务日期。

### 日期顺序

以下规则按关键失败处理：

- `shipped_date` 和 `order_date` 都非空时，`shipped_date` 不得早于 `order_date`
- `required_date` 和 `order_date` 都非空时，`required_date` 不得早于 `order_date`

`shipped_date` 晚于 `required_date` 表示延期发货代理状态，属于有效业务事实，不是数据质量失败。

源 Schema 没有实际送达日期。不得从 `required_date`、`shipped_date` 或运费推断实际送达、运输时长或承运商最终配送绩效。

### 日期空值

- `shipped_date` 为空表示订单尚未进入认证销售，不代表取消。
- `required_date` 为空时，发货及时性代理指标为空。
- `order_date` 为空时，不计算依赖订单创建日期的时长。
- `shipped_date` 非空但 `order_date` 为空时，订单仍可按发货日期进入销售候选，配送时长相关指标为空，并生成警告。
- `shipped_date` 非空但没有有效订单明细时，按关键失败处理。

### 日期变更与重算

- `shipped_date` 从空值变为日期时，订单进入认证销售。
- `shipped_date` 从日期变为空值时，订单从认证销售移除。
- `shipped_date` 改为其他日期时，原销售日期和新销售日期都要重算。
- `order_date` 或 `required_date` 更正时，重算受影响配送代理指标。
- 客户、员工、商品、价格、数量、折扣或运费更正时，重算受影响产品结果。

标准重跑和补数窗口为最近 90 天。超过 90 天的历史更正需要产品 Owner 和平台 Owner 双重批准。

## CDC、重复与顺序异常

### 已确认处理元数据

| 元数据 | 质量用途 |
|---|---|
| `_dms_transport_operation` | 校验 DMS 传输层操作类型 |
| `_dms_operation` | 标准化 INSERT、UPDATE 和 DELETE |
| `_dms_commit_ts` | CDC 源提交时间和 Full Load 任务启动时间 |
| `_dms_change_seq` | 任务级事件顺序 |
| `_dms_stream_position` | PostgreSQL 日志流位置 |
| `_dms_source_schema` | 验证源 Schema |
| `_dms_source_table` | 验证批准源表 |
| `_dataset_generation` | 区分受控数据代际 |
| `_ingested_at_utc` | Databricks 摄取审计时间 |
| `_source_file` | 源文件追踪和最终排序 |
| `_source_file_modification_time` | 文件审计 |
| `_pipeline_update_id` | Pipeline 更新追踪 |
| `_dms_load_phase` | 区分 Full Load 和 CDC |
| `_dataset_generation_rank` | 数据代际顺序 |
| `_rescued_data` | Schema 漂移救援数据 |

这些字段属于平台元数据，不属于 Northwind 业务字段。

### 元数据合法性

以下规则失败时按关键失败处理：

- `_dms_operation` 只能为 `INSERT`、`UPDATE`、`DELETE`
- CDC 的 `_dms_transport_operation` 只能为 `I`、`U`、`D`
- CDC 两种操作标识必须语义一致
- Full Load 的 `_dms_operation` 必须为 `INSERT`
- Full Load 的 `_dms_transport_operation` 允许为空
- `_dms_commit_ts` 必须可严格解析为 UTC Timestamp
- `_dms_change_seq` 非空时必须可转换为 `DECIMAL 38,0`
- `_dms_source_schema` 必须为 `public`
- `_dms_source_table` 必须属于批准的 14 张表
- `_dataset_generation` 和 `_dataset_generation_rank` 必须属于批准配置
- 数据代际顺序必须为不可复用的正整数
- 认证结果中的 `_rescued_data` 必须为空

### 确定性版本顺序

同一业务键的版本优先级固定如下：

1. `_dataset_generation_rank`
2. CDC 高于 Full Load
3. `_dms_change_seq`
4. `_dms_commit_ts`
5. `_dms_stream_position`
6. `_ingested_at_utc`
7. `_source_file`

重复文件、任务重试和乱序事件必须按该顺序得到唯一结果。

跨表事务顺序不作为下游依赖。跨表一致性由外键宽限、质量检查和发布门禁保证。

### 重复类型

| 异常 | 处置 |
|---|---|
| 同一文件被重复发现 | Bronze 可保留可追踪事件，Silver 结果必须幂等 |
| 同一业务键收到完全相同版本和载荷 | 记录重复计数，Silver 只保留一个当前版本 |
| 同一业务键收到相同版本但不同载荷 | 关键失败并隔离全部冲突记录 |
| 旧事件晚于新事件到达 | 按确定性版本顺序处理，不得覆盖新版本 |
| DELETE 后重新 INSERT | 按版本顺序恢复新的当前记录 |
| 重试产生重复 Gold 聚合 | 关键失败，回滚本次候选结果并保留最近认证结果 |

### 删除事件

Bronze 保留 DELETE 事件历史。

Silver 收到有效 DELETE 后移除对应业务键的当前记录。Gold 在后续刷新中移除由该记录产生的当前认证结果。

源端删除从 Silver 当前状态和后续 Gold 中移除的目标时限为 15 分钟。

DELETE 缺失业务键、操作类型矛盾或版本顺序不可确定时，按关键失败处理。

父记录删除造成的持久外键孤儿适用 30 分钟宽限。宽限结束后仍未恢复时，隔离受影响子记录并阻断依赖产品。

### 数据代际

初始数据代际为 `v1`，对应 `_dataset_generation_rank` 值一。

以下场景创建新数据代际：

- 重新执行 DMS Full Load
- 更换 DMS 任务且无法安全续接原复制槽
- 更换源数据库或源目录
- 当前代际发生不可修复的数据污染

新代际必须从 Full Load 加 CDC 开始。只有完成全量对账、CDC 连续性验证、关键质量门禁和产品对账后，才能原子切换认证引用。

旧代际保持只读并按保留策略清理。不同代际不得无条件混合形成当前状态。

## 产品级质量要求

### 每日销售

每日销售必须满足以下要求：

- 只包含 `shipped_date` 非空的订单
- 销售日期直接使用 `shipped_date`
- 每个销售日期最多一条汇总记录
- 已发货订单至少包含一条通过质量检查的订单明细
- 订单数按 `order_id` 去重
- 客户数按非空 `customer_id` 去重
- 商品数量使用有效订单明细的 `quantity`
- 商品销售金额使用 `order_details.unit_price`
- 运费只在订单粒度累计一次
- 金额恒等式通过
- 输入和输出水位完整

未发货订单进入每日销售时按关键失败处理。

### 客户价值

客户价值必须满足以下要求：

- 每个快照日期和当前客户最多一条记录
- 当前客户全集来自 Silver `customers`
- 没有已发货销售的当前客户保留零值记录
- 没有已发货销售的当前客户平均商品净订单金额保持为空，不得执行除零计算
- 只累计 `customer_id` 可归属的已发货订单
- `customer_id` 为空的订单不归属任何客户
- 运费按订单粒度累计，空值按零计入金额并保留运费缺失订单数
- 当前公司名变化可以重述历史展示属性
- 稳定归属始终使用 `customer_id`
- 普通分析师读取公司名时应用已确认 Column Mask

### 商品与品类表现

商品日销售表现必须满足以下要求：

- 每个销售日期和商品最多一条记录
- 只包含已发货订单中的有效订单明细
- 销售金额使用订单明细交易价格
- 当前商品价格不得回填历史交易金额
- 商品归属使用 `product_id`
- 当前品类属性来自 Silver 当前状态
- 品类为空时保持为空，不生成未知品类
- 运费不得分摊到商品或品类

商品库存观察快照必须满足以下要求：

- 每个快照日期和商品最多一条记录
- 当前商品全集来自 Silver `products`
- 库存、在途和补货阈值遵守非负或空值规则
- 停售状态只由零和一映射
- 当前库存快照不得被解释为历史库存
- `units_in_stock` 和 `units_on_order` 的指标替代保留缺失标识

### 员工销售表现

员工销售表现必须满足以下要求：

- 每个销售日期和员工最多一条记录
- 只包含 `employee_id` 可归属的已发货订单
- 归属依据只使用 `orders.employee_id`
- 不使用 `employee_territories` 分摊销售
- 当前姓名、职位和汇报关系可以重述历史展示属性
- 稳定归属始终使用 `employee_id`
- 运费不得进入员工销售金额
- 普通分析师读取员工姓名时应用已确认 Column Mask

### 配送表现

配送表现必须满足以下要求：

- 每个订单最多一条当前记录
- 同时覆盖已发货和未发货订单
- `days_to_ship` 只在 `order_date` 和 `shipped_date` 都非空时计算
- `shipped_by_required_date_proxy_flag` 只在 `required_date` 和 `shipped_date` 都非空时计算
- `days_shipped_after_required_date` 在延期发货时记录正数，在按期或提前发货时记录零
- 未发货订单的发货时长和及时性代理指标为空
- 未发货订单的 `open_order_days` 使用快照日期减 `order_date`
- 承运商为空时保持为空
- 不发布准时送达率
- 不发布实际运输时长
- 不声明承运商最终配送绩效

把发货及时性代理指标描述为实际送达指标时，按关键质量失败处理。

## 对账要求

### Full Load 对账

Full Load 完成后必须验证以下事项：

- 14 张批准源表全部完成
- DMS 没有失败表或挂起表
- 62 个摄取字段与字段白名单一致
- Restricted 字段扫描结果为零
- 源端、DMS 落地、Bronze 和 Silver 行数可以按表解释
- Silver 主键和组合主键重复数为零
- 持久外键孤儿数为零
- 代表性表覆盖 INSERT、UPDATE、DELETE 和删除后重插
- 每张表至少验证一条 CDC 事件的操作、提交时间、变更序列和日志位置
- 金额按照定点小数和 `HALF_UP` 规则独立重算一致
- 运费只在订单粒度累计一次
- 认证销售只包含 `shipped_date` 非空订单
- 配送指标没有声明实际送达事实
- 当前数据代际完整且可追溯

Full Load 对账完成前，Gold 只能保持 `candidate` 或 `blocked`，不得更新为 `certified`。

### 持续 CDC 对账

每次增量发布至少执行以下对账：

- DMS 已处理记录数与 Bronze 新增事件数按表比较
- Bronze 到 Silver 的插入、更新和删除数量可解释
- Silver 当前状态变化与业务键版本顺序一致
- Gold 已发货订单数与 Silver 认证订单范围一致
- Gold 净销售额与独立订单明细重算一致
- Gold 运费与订单粒度独立汇总一致
- 输入水位不早于最近一次已认证输入水位
- 输出覆盖范围与本次变更影响范围一致
- Restricted 字段扫描结果为零
- 认证结果中的 `_rescued_data` 为空

计数差异必须能够由重复事件、隔离记录、DELETE、迟到事件或当前运行边界解释。无法解释的差异按关键失败处理。

### 产品间一致性

在相同认证范围和水位下，以下结果必须一致：

- 每日销售商品净销售额等于按客户汇总后的可归属销售加未归属客户销售
- 每日销售商品净销售额等于按商品汇总后的销售
- 每日销售可归属员工净销售额等于员工销售表现汇总
- 商品与品类表现中的商品数量等于有效订单明细数量汇总
- 含运费订单总额中的运费只出现一次
- 配送产品中的已发货订单范围与销售产品中的已发货订单范围一致

由于客户和员工外键允许为空，客户价值与员工销售表现的可归属总额可以小于每日销售总额。该差额必须由空归属记录明确解释，不得通过虚假维度成员消除。

### 水位与新鲜度

数据新鲜度从 CDC `_dms_commit_ts` 到 Gold 最近刷新 UTC 时间计算。Full Load 记录不参与常规 CDC 新鲜度统计。

| 指标 | 质量目标 |
|---|---|
| 端到端新鲜度 P95 | 15 分钟内 |
| 最大允许延迟 | 30 分钟 |
| 日终认证完成 | 每日 02:00 `Asia/Tokyo` 前 |
| 源端删除传播 | 15 分钟目标 |
| 标准补数窗口 | 90 天 |

Gold 新鲜度超过 30 分钟时不得认证发布。

## 异常隔离与处置

### 隔离触发

以下异常必须进入受控隔离区：

- 主键缺失
- 主键版本冲突不可确定
- 非空外键超过 30 分钟仍为孤儿
- 数量、交易单价、折扣、运费或库存违反关键范围
- 日期顺序违反关键规则
- DMS 操作类型缺失、非法或矛盾
- DMS 提交时间或变更序列无法解析
- 数据代际非法
- 金额转换失败或溢出
- Restricted 字段命中
- 认证字段进入 `_rescued_data`
- 已发货订单没有有效订单明细
- Gold 业务粒度重复
- 对账差异无法解释

### 隔离证据

`ops.quarantine_records` 至少保存以下逻辑信息：

- 环境
- 数据代际
- 源 Schema
- 源表
- 业务键
- 规则标识
- 质量级别
- 发现时间
- 来源文件
- Pipeline 更新标识
- DMS 操作类型
- DMS 提交时间
- 错误摘要
- 受影响数据产品
- 处置状态
- 重放记录
- 证据位置

隔离区保留 90 天。隔离记录不得向普通分析师开放。

### 处置原则

- 不直接修改 Landing 文件
- 不直接修改 Bronze 原始事件
- 不在 Silver 静默纠正源值
- 源业务值错误由源系统更正并通过 CDC 重新进入平台
- 平台解析或映射错误由工程团队修复后受控重放
- 同一数据代际可安全恢复时优先在原代际重放
- 当前代际受到不可修复污染时创建新数据代际
- 重放前验证输入文件、Checkpoint 和 Schema State 完整性
- 禁止手工删除或编辑 Lakeflow Checkpoint 和 Auto Loader Schema State
- 重放后必须重新执行主键、外键、金额、CDC 和产品对账

关键异常解决后，只有质量检查、对账和发布门禁全部重新通过，受影响产品才能恢复为 `certified`。

### 人工处置

警告由 `grp_northwind_stewards` 在下一个工作日内完成评估、分派或记录接受理由。

关键失败由平台值班立即创建事件。工程团队负责技术修复，Steward 负责数据判定，产品 Owner 负责业务影响和恢复发布确认。

Restricted 数据命中、疑似泄露和权限异常必须同时通知 `grp_northwind_security`。此类事件不得通过普通质量豁免恢复发布。

## 质量结果与审计

### Ops 记录

| Ops 对象 | 用途 | 保留期 |
|---|---|---|
| `ops.data_quality_results` | 保存规则执行结果、失败数量、范围和状态 | 400 天 |
| `ops.source_reconciliation` | 保存源到各层和产品间对账结果 | 400 天 |
| `ops.quarantine_records` | 保存隔离记录和处置证据 | 90 天 |
| `ops.schema_drift_events` | 保存 Schema 漂移事件 | 400 天 |
| `ops.publish_watermarks` | 保存输入水位、输出水位和认证状态 | 400 天 |
| `ops.job_runs` | 保存 Job 和 Pipeline 运行证据 | 400 天 |

每次规则执行至少记录以下信息：

- 规则标识
- 规则版本
- 环境
- 数据代际
- 数据层
- 源表或数据产品
- Pipeline 更新标识
- 输入水位
- 检查开始和结束 UTC 时间
- 检查记录数
- 失败记录数
- 警告记录数
- 结果状态
- 隔离记录引用
- 受影响产品
- 执行身份
- 证据位置

结果状态不得由模型推断。只有真实运行记录可以证明检查已执行或通过。

### 规则标识

质量规则使用稳定分类前缀：

| 前缀 | 范围 |
|---|---|
| `DQ-SCHEMA` | 表、字段、类型、白名单和漂移 |
| `DQ-PK` | 主键非空和唯一性 |
| `DQ-FK` | 外键引用和宽限 |
| `DQ-NULL` | 必填字段和空值处置 |
| `DQ-RANGE` | 数量、价格、折扣、运费和库存 |
| `DQ-DATE` | 日期顺序和日期语义 |
| `DQ-CDC` | 操作类型、顺序、重复、删除和代际 |
| `DQ-AMOUNT` | 定点小数、舍入和金额恒等式 |
| `DQ-RECON` | 源到目标及产品间对账 |
| `DQ-PRODUCT` | 产品粒度、范围和指标 |
| `DQ-SECURITY` | Restricted 字段、权限和敏感数据 |
| `DQ-FRESHNESS` | 水位、延迟和日终认证 |

规则标识一旦被发布记录引用，不得复用为不同语义。规则变更必须增加版本并保留旧版本解释。

## 严重等级与告警阈值

### 质量告警

| 监控项 | Warning | Critical |
|---|---|---|
| 关键数据质量失败数 | 不适用 | 大于零 |
| `_rescued_data` | 任一运行大于零 | 连续两次运行大于零或涉及认证字段 |
| Restricted 字段扫描 | 不适用 | 发现任一字段或值 |
| 持久外键孤儿 | 宽限期间记录并监控 | 超过 30 分钟仍大于零 |
| Silver 主键重复 | 不适用 | 大于零 |
| Gold 粒度重复 | 不适用 | 大于零 |
| 无法解释的对账差异 | 首次发现并进入调查 | 发布前仍未解释 |
| Gold 数据新鲜度 | 超过 20 分钟 | 超过 30 分钟 |
| 日终认证 | 01:50 前未完成 | 02:00 前未完成 |
| Pipeline 运行 | 首次失败 | 三次自动重试后仍失败 |
| Pipeline 运行时长 | 超过 45 分钟 | 超过 60 分钟 |

### 摄取与平台告警

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

### 业务警告

以下情况生成警告，不自动修改源值：

- 文本拼写、空白或格式异常
- `us_states` 中 Iowa 缩写 `IO`
- `us_states` 中其他未被外键支持的异常缩写
- `customer_demographics` 或 `customer_customer_demo` 为空
- 源日期、运费或库存字段的空值比例显著变化
- 当前商品价格与历史订单明细交易价格不同
- 当前名称或组织关系变化导致历史展示属性重述
- 客户或员工标识为空导致订单未归属
- 已发货订单的 `order_date` 为空
- DMS CDC 文件因时间阈值提前刷新而小于目标文件尺寸

可空字段的空值比例以同一环境、同一表和同一字段最近 30 次已认证运行的中位数为基线。至少积累 7 次已认证运行后，当前空值比例与基线相差达到 10 个百分点时生成警告。基线不足时只记录观测值，不据此阻断发布。

样例中的 Iowa 缩写 `IO` 必须保留原值并生成警告，不得自动修正。

### 故障等级

| 等级 | 条件 | 响应目标 |
|---|---|---|
| Sev 1 | 数据丢失、敏感数据泄露、Restricted 字段进入平台、不可恢复数据损坏 | 15 分钟内确认，立即升级平台和安全 Owner |
| Sev 2 | 新鲜度超过 30 分钟、Job 重试后仍失败、DMS 停止、日终认证失败、关键质量门禁失败、审计中断 | 30 分钟内确认，4 小时内恢复 |
| Sev 3 | Schema 漂移、非关键质量警告、可解释的非阻断对账偏差、单个非认证报表问题 | 下一个工作日处理 |

Critical 告警必须创建值班事件。Restricted 字段扫描命中、疑似数据泄露和不可恢复数据损坏直接按 Sev 1 处理。

### 告警渠道

AWS 告警通过 `northwind-data-<environment>-alerts` SNS Topic 投递。

Databricks 告警通过 `northwind-data-<environment>-ops` System Destination 投递。

两个渠道必须进入同一平台值班事件流并生成可追踪事件编号。

升级顺序固定为平台值班、平台 Owner、产品 Owner。涉及敏感数据、权限或审计时同时通知安全 Owner。

## 发布门禁

每次 Gold 认证发布必须同时满足以下条件：

- 适用关键质量规则全部通过
- 增量对账成功
- Full Load 场景已完成全量对账
- 数据新鲜度未超过 30 分钟
- 输入水位不早于最近一次已认证输入水位
- 输出覆盖范围与本次变更影响范围一致
- Restricted 字段扫描结果为零
- `_rescued_data` 未进入认证结果
- 当前数据代际属于批准配置
- 金额定点小数转换无失败和溢出
- 认证销售只包含 `shipped_date` 非空订单
- 已发货订单至少包含一条有效订单明细
- 运费只在订单粒度累计一次
- 配送指标未声明实际送达事实
- 五类产品的业务粒度唯一
- 质量结果、对账结果和发布水位完整记录

门禁失败时：

- 受影响产品更新为 `blocked`
- 本次候选结果不得替代最近认证结果
- 认证水位不得推进
- 生成 Critical 告警
- 创建隔离或调查记录
- 完成修复、重放和重新对账后才能恢复认证

## 验收与演练要求

### 首次生产发布前

首次生产发布前必须完成以下质量演练：

- 14 张表 Full Load 对账
- 62 个字段白名单验证
- Restricted 字段零命中验证
- 主键非空和唯一性验证
- 13 个外键关系验证
- 30 分钟外键乱序宽限验证
- INSERT、UPDATE、DELETE 和删除后重插验证
- 重复文件和任务重试幂等验证
- 乱序 CDC 验证
- DMS 操作标识一致性验证
- `_dms_commit_ts` 和 `_dms_change_seq` 解析失败隔离验证
- `_rescued_data` 告警和阻断验证
- 金额定点小数、舍入和溢出验证
- 运费订单粒度验证
- 已发货销售范围验证
- 产品业务粒度验证
- Gold 发布门禁失败回滚验证
- 最近认证结果保留验证
- 90 天重跑验证
- RPO 和 RTO 演练
- 告警渠道到达验证
- 审计证据保留验证

这些条目是必须执行的验收要求，不表示当前环境已经完成或通过。

### 持续运行

持续运行期间必须执行：

- 每次增量发布的关键质量检查
- 每次增量发布的源到目标对账
- 每次增量发布的产品间一致性检查
- 每次发布前的 Restricted 字段扫描
- 每次发布前的 `_rescued_data` 检查
- 每日 01:30 `Asia/Tokyo` 日终认证
- 每日开放订单和库存观察快照检查
- 每季度生产访问评审
- 源 Schema 变化时的全量影响评估
- 数据代际切换前的全量质量验收
- 质量规则变更后的回归验证

## 变更控制

以下变化必须更新本文并完成相应审批：

- 源表、字段、类型、长度、可空性、主键或外键变化
- DMS 表清单、字段白名单、元数据或任务模式变化
- CDC 排序、删除、去重或数据代际规则变化
- 业务指标、销售范围、日期语义或运费口径变化
- 关键规则、警告规则、阈值或处置方式变化
- Gold 产品粒度、维度或指标变化
- Restricted 和 Confidential 分类变化
- SLA、恢复目标、保留期或告警渠道变化
- Ops 证据结构和发布门禁变化

变更必须评估源映射、DMS、S3、Auto Loader、Bronze、Silver、Gold、Ops、权限、血缘、审计、重跑、SLA、成本和下游兼容性。

旧规则是否失效必须明确记录。不得静默覆盖已被历史发布记录引用的规则版本。
