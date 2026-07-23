<!--
文件用途：记录销售、折扣、日期、配送、数据键、CDC、空值、质量异常和敏感数据处置规则，是 Agent 判断业务口径和数据口径的权威输入。
维护责任：由用户手动维护并确认。规则发生变化时必须直接修改本文，注明生效范围，并明确被替代规则是否失效。Agent 可以读取、引用、检查一致性和指出冲突，不得擅自修改已确认规则。
事实边界：源表、字段、数据类型、主键、外键和可空性只以 source-schema/northwind-schema.sql 为准。平台元数据、指标定义、质量处置和治理方式以本文及已确认的项目需求文件为准，不代表相关任务已经部署、运行或验证。
优先关系：源结构事实遵循 Northwind SQL 文件。项目架构、治理、SLA 和运行参数遵循已确认的项目需求文件。业务指标与数据处置口径遵循本文。文件之间出现冲突时必须先完成文档变更和人工确认，禁止由 Agent 自行选择口径。
内容边界：只记录已确认的业务定义和数据规则。不得写入 SQL 实现、生成代码、测试期望值、密钥、真实连接信息或未经证实的运行状态。
-->

# 已确认业务与数据规则

## 文档适用范围

本文适用于 Northwind 销售分析项目的 Landing、Bronze、Silver、Gold 和 Ops 数据处理过程，覆盖以下内容：

- 源数据粒度与业务键
- CDC 排序、去重和删除
- 日期语义、迟到数据和历史回补
- 销售、折扣、运费和数量指标
- 客户、商品、品类、员工和配送归属
- 空值、外键、异常和发布处置
- 敏感字段、发布权限和列级保护

本文只定义规则，不证明规则已经执行。任何已执行、已通过或已认证状态都必须由真实环境中的运行记录、质量结果和发布证据确认。

## 源数据粒度与业务键

### 订单与订单明细

`orders` 每行代表一张订单，业务粒度为一个 `order_id`。`order_id` 是主键且不得为空。

`order_details` 每行代表一张订单中的一个商品明细，业务粒度由 `order_id` 和 `product_id` 共同确定。两个字段组成组合主键，均不得为空。

同一订单中的同一商品在源表中最多出现一行。商品数量通过 `quantity` 表示，不得通过复制订单明细表达数量。

### 核心实体键

| 实体 | 主键 |
|---|---|
| 客户 | `customer_id` |
| 员工 | `employee_id` |
| 商品 | `product_id` |
| 品类 | `category_id` |
| 供应商 | `supplier_id` |
| 承运商 | `shipper_id` |
| 大区 | `region_id` |
| 销售区域 | `territory_id` |

所有主键和组合主键必须完整保留源值。源 Schema 没有序列或统一代理键，目标层不得替换源业务键，也不得把自动生成编号写回源键字段。

### 关系与可空性

所有可依赖关系只来自源 DDL 中的外键。

`orders.customer_id`、`orders.employee_id` 和 `orders.ship_via` 在源 Schema 中允许为空。空值必须保持为空，不得生成未知客户、未知员工或未知承运商等伪造维度成员。

`products.supplier_id` 和 `products.category_id` 允许为空。空值商品仍保留商品事实，供应商或品类属性保持为空。

`employees.reports_to` 允许为空。空值表示当前源数据没有上级员工引用，可用于表示员工层级根节点。

非空外键必须引用有效父记录。DMS 按表落地且不保留跨表事务顺序，短暂外键孤儿允许 30 分钟处理宽限。宽限结束后仍未恢复的记录按关键质量失败处理。

### 当前属性原则

客户公司名、商品名、品类名、供应商名、员工姓名、员工职位、上级关系和承运商名来自 Silver 当前状态。

源 Schema 没有属性有效期。历史销售记录在重新发布时可以显示最新名称和最新组织关系。稳定归属始终使用源标识符，名称变化不得改变订单、客户、商品或员工的源键归属。

不得依据当前属性伪造历史有效期，也不得声称可以还原源系统未提供的历史组织结构。

## CDC、去重与删除

### 元数据地位

DMS 和 Databricks 生成的元数据属于平台处理元数据，不属于 Northwind 源业务字段。它们只用于摄取审计、排序、去重、删除和恢复，不得替代源业务日期或业务键。

已确认使用以下 DMS 元数据：

- `_dms_transport_operation`
- `_dms_operation`
- `_dms_commit_ts`
- `_dms_change_seq`
- `_dms_stream_position`
- `_dms_source_schema`
- `_dms_source_table`
- `_dataset_generation`

已确认使用以下 Databricks 审计元数据：

- `_ingested_at_utc`
- `_source_file`
- `_source_file_modification_time`
- `_pipeline_update_id`
- `_dms_load_phase`
- `_dataset_generation_rank`
- `_rescued_data`

### 操作类型

CDC 记录的 `_dms_operation` 只能取 `INSERT`、`UPDATE` 或 `DELETE`。

CDC 记录的 `_dms_transport_operation` 只能取 `I`、`U` 或 `D`，并且必须与 `_dms_operation` 语义一致。

Full Load 记录的 `_dms_operation` 固定为 `INSERT`。Full Load 记录的 `_dms_transport_operation` 允许为空。

操作类型缺失、非法或相互矛盾时，受影响记录进入隔离，受影响数据产品停止认证发布。

### 最新版本选择

Silver 按源业务键保留当前最新版本。发生重复文件、任务重试、乱序事件或删除后重插时，必须得到确定且幂等的结果。

同一业务键的版本优先级按以下顺序判断：

1. `_dataset_generation_rank`
2. CDC 高于 Full Load
3. `_dms_change_seq`
4. `_dms_commit_ts`
5. `_dms_stream_position`
6. `_ingested_at_utc`
7. `_source_file`

`_dms_change_seq` 必须转换为 `DECIMAL 38,0` 后参与排序。无法转换的记录进入隔离。

下游不得依赖跨表事务顺序。跨表一致性通过外键宽限、质量检查和发布门禁保证。

### 删除规则

Bronze 保留追加式 CDC 事件历史，不因源端 DELETE 物理移除历史事件。

Silver 收到有效 DELETE 后，从当前状态中移除对应业务键记录。

后续 Gold 刷新必须移除由该记录产生的当前认证结果。源端删除从 Silver 当前状态和后续 Gold 结果中移除的目标时限为 15 分钟。

删除父记录后产生的持久外键孤儿遵循 30 分钟宽限规则。宽限结束后仍未恢复时，相关记录进入隔离，并阻断受影响 Gold 数据产品发布。

删除事件不得被改写为普通更新，也不得通过生成虚假失效标识替代源端删除语义。

## 日期、事件时间与迟到数据

### 源日期语义

| 字段 | 已确认语义 |
|---|---|
| `orders.order_date` | 订单创建日期 |
| `orders.required_date` | 源系统记录的要求发货日期 |
| `orders.shipped_date` | 源系统记录的实际发货日期，同时作为认证销售归属日期 |

三个字段都是 PostgreSQL `date`，不含时分秒和时区。目标层保持 `DATE`，不得执行时区换算，也不得推导源系统未提供的小时或分钟。

平台调度时区固定为 `Asia/Tokyo`。运行审计、摄取时间和 DMS 提交时间统一记录为 UTC。

### 销售归属日期

认证销售的 `sales_date` 直接取 `orders.shipped_date`。

`orders.order_date` 不用于认证销售归属。它只用于订单创建分析、发货处理耗时和开放订单天数计算。

`orders.required_date` 只用于发货处理代理指标，不用于销售归属。

### 发货确认与开放订单

只有 `orders.shipped_date` 非空的订单进入认证销售口径。

`orders.shipped_date` 为空的订单不计入每日销售、客户价值、商品与品类销售和员工销售表现。此类订单继续进入配送表现数据产品，并作为开放订单计算 `open_order_days`。

源 Schema 没有取消状态。未发货订单不得自动解释为取消订单、失败订单或零销售订单。

### 迟到更正与重算

CDC 对以下字段产生更正时，必须重算受影响销售日期和相关累计结果：

- `orders.shipped_date`
- `orders.customer_id`
- `orders.employee_id`
- `orders.freight`
- `order_details.product_id`
- `order_details.unit_price`
- `order_details.quantity`
- `order_details.discount`
- 影响当前展示属性的客户、商品、品类、供应商、员工或承运商字段

`shipped_date` 从空值变为日期时，订单从开放订单转入认证销售。

`shipped_date` 从日期变为空值时，订单从认证销售中移除并重新进入开放订单口径。

`shipped_date` 改为其他日期时，原销售日期和新销售日期都必须重算。

标准重跑和补数窗口为最近 90 天。超过 90 天的历史更正不得丢弃，必须通过产品 Owner 和平台 Owner 双重批准后执行受控回补。

### 数据新鲜度与发布水位

正常 CDC 数据新鲜度从 `_dms_commit_ts` 到 Gold `last_refreshed_at_utc` 计算。端到端新鲜度目标为 P95 在 15 分钟内，最大允许延迟为 30 分钟。

超过 30 分钟到达的数据仍必须处理，同时记录 SLA 违约和迟到原因，不得因超过时限而丢弃。

Full Load 记录不参与正常 CDC 新鲜度统计。

只有关键质量规则全部通过、增量对账成功且新鲜度未超过最大允许延迟时，才允许推进认证发布水位。失败运行和被阻断运行不得推进水位。

### 日终认证边界

每日认证任务在 01:30 按 `Asia/Tokyo` 运行，认证前一日历日期，并在 02:00 前完成。

源日期不含时区，因此前一日历日期只用于日终发布边界，不改变 `shipped_date` 的源值。

失败运行不得推进已认证水位，也不得覆盖最近一次已认证结果。

## 认证销售范围

所有认证销售指标同时满足以下条件：

- `orders.shipped_date` 非空
- 订单通过适用的关键数据质量规则
- 订单至少包含一条通过关键数据质量规则的订单明细
- 参与计算的订单明细使用源业务键与订单正确关联

源 Schema 没有以下字段和事实：

- 订单状态
- 取消状态
- 付款状态
- 退货状态
- 退款状态
- 货币代码
- 实际送达日期

项目不得推断取消、付款、退货、退款或实际送达结果，也不得把源金额声明为美元或其他具体币种。

## 金额、折扣、数量与运费

### 数据类型与舍入

源金额和折扣字段使用 PostgreSQL `real`。认证计算前必须转换为定点小数。

| 字段或结果 | 认证类型 |
|---|---|
| `order_details.unit_price` | `DECIMAL 18,4` |
| `products.unit_price` | `DECIMAL 18,4` |
| `orders.freight` | `DECIMAL 18,4` |
| `order_details.discount` | `DECIMAL 9,6` |
| 派生金额 | `DECIMAL 20,4` |

认证金额采用 `HALF_UP` 规则保留四位小数。认证计算不得直接使用 FLOAT 或 DOUBLE。

### 订单行金额

订单行毛额使用订单明细交易单价乘 `quantity`，随后按 `HALF_UP` 保留四位小数。

订单行折扣额使用已舍入的订单行毛额乘转换后的 `discount`，随后按 `HALF_UP` 保留四位小数。

订单行净销售额使用已舍入的订单行毛额减已舍入的订单行折扣额。

订单、日期、客户、商品、品类和员工金额都从已舍入的订单行金额汇总，不得先汇总浮点数再舍入。

销售金额必须使用 `order_details.unit_price`。`products.unit_price` 只表示当前商品目录价格，不得回填或覆盖历史订单明细交易价格。

### 折扣规则

`order_details.discount` 的有效范围包含零和一。

折扣小于零或大于一时，记录进入隔离，受影响销售结果停止认证发布。不得裁剪为边界值，也不得改写为零。

折扣等于零表示无折扣。折扣等于一表示订单行净销售额为零。

### 数量规则

`order_details.quantity` 必须大于零。

订单商品数量是通过质量检查的 `quantity` 之和。不得使用订单明细行数替代商品数量。

商品和品类订单数按 `order_id` 去重计算，避免一个订单中的多个明细造成重复计数。

### 运费规则

`orders.freight` 位于订单粒度。

运费为空时，认证金额按零计入，同时保留运费缺失标识。运费小于零时按关键质量失败处理。

同一订单的运费只能累计一次，不得因连接多个订单明细而重复累计。

运费可以汇总到每日销售和客户价值。商品、品类和员工销售表现不分摊运费。

含运费订单总额等于订单商品净销售额加订单运费。

平均订单金额使用商品净销售额除以已发货订单数，不含运费。已发货订单数为零时，平均订单金额保持为空，不得以零代替或执行除零计算。

### 货币规则

所有金额统一标记为 `source_currency_amount`。

源 Schema 没有货币代码。项目不做汇率换算，不声明具体币种，也不合并外部汇率数据。

## 数据产品归属规则

### 每日销售

每日销售按 `sales_date` 聚合，每个日期一行。

订单数按 `order_id` 去重。客户数只统计非空 `customer_id` 的去重值。商品数量汇总通过质量检查的 `quantity`。

同一订单无论包含多少订单明细，订单数和运费都只计算一次。

### 客户价值

客户价值以 `silver.customers` 中的全部当前客户为基础，每个 `snapshot_date` 和 `customer_id` 一行。

没有已发货订单的当前客户保留一行，金额和计数为零，平均商品净订单金额、首次销售日期、最近销售日期和最近购买间隔保持为空。

客户价值中的运费空值按零计入金额，同时必须保留运费缺失订单数；同一订单的运费和缺失计数都只能累计一次。

首次销售日期和最近销售日期都基于 `shipped_date`。最近购买间隔等于快照日期减最近销售日期。

`orders.customer_id` 为空的已发货订单仍计入每日销售、商品与品类销售以及适用的员工销售结果，但不归属于任何客户价值记录，客户去重数也不计入该空值。此类记录生成数据质量警告，不得创建未知客户。

客户价值表示截至快照日期的已观察历史价值，不提供预测客户终身价值。

### 商品与品类表现

商品与品类销售按 `sales_date` 和 `product_id` 聚合。

销售金额使用订单明细交易价格。商品当前目录价格只进入库存观察快照，不进入历史销售金额计算。

商品的品类和供应商来自当前 Silver 属性。`category_id` 或 `supplier_id` 为空时保持为空，不得生成未知品类或未知供应商。

库存快照表示 Pipeline 观察时点的当前状态。源商品表没有更新时间，因此库存快照不得声明为源系统日终库存。

`products.discontinued` 为零时映射为未停售，为一时映射为已停售。其他值进入隔离并阻断受影响产品数据发布。

可用供应数量等于 `units_in_stock` 和 `units_on_order` 的空值按零处理后相加。

补货标识遵循以下规则：

- 商品已停售时为 false
- 商品未停售且 `reorder_level` 非空，并且可用供应数量小于等于 `reorder_level` 时为 true
- 商品未停售且 `reorder_level` 非空，并且可用供应数量大于 `reorder_level` 时为 false
- `reorder_level` 为空时保持为空

### 员工销售表现

订单只按 `orders.employee_id` 归属员工。

`orders.employee_id` 为空的已发货订单仍计入每日销售、客户价值和商品与品类销售，但不进入任何员工销售记录。此类记录生成数据质量警告，不得创建未知员工。

员工与销售区域通过 `employee_territories` 形成多对多关系，订单表没有 `territory_id`。员工区域关系只作为当前员工属性，不得用于订单区域分摊、业绩重复归属或区域销售推断。

员工姓名、职位和上级关系使用当前 Silver 属性。源 Schema 没有历史组织有效期，不得把当前组织关系解释为订单发生时的历史组织关系。

### 配送表现

配送表现以 `order_id` 为粒度，包含已发货订单和未发货订单。

`days_to_ship` 等于 `shipped_date` 减 `order_date`，只在两个日期都非空时计算。

`shipped_by_required_date_proxy_flag` 只在 `shipped_date` 和 `required_date` 都非空时计算。`shipped_date` 小于等于 `required_date` 时为 true，晚于 `required_date` 时为 false。

`days_shipped_after_required_date` 在 `shipped_date` 晚于 `required_date` 时记录正数，在按期或提前发货时记录零。任一所需日期为空时保持为空。

未发货订单的 `days_to_ship`、`shipped_by_required_date_proxy_flag` 和 `days_shipped_after_required_date` 保持为空。

未发货订单的 `open_order_days` 等于快照日期减 `order_date`。`order_date` 为空时保持为空。

`orders.ship_via` 为空时，承运商标识和承运商名称保持为空，不得生成未知承运商。

源 Schema 没有实际送达日期。`required_date` 与 `shipped_date` 的比较只表示发货处理代理指标。配送数据产品不得发布准时送达率、实际运输时长或承运商最终配送绩效。

## 空值与缺失值

### 保留原则

源字段允许为空时，目标层原则上保留空值。只有本文明确规定的指标计算允许采用替代值，并且必须同时保留缺失标识。

当前明确允许的指标替代只有以下两项：

- `orders.freight` 为空时按零计入金额，并保留运费缺失标识
- `units_in_stock` 和 `units_on_order` 为空时，在可用供应数量计算中按零处理

替代值只服务于指定指标，不得覆盖 Silver 中的原始空值。

### 禁止伪造维度值

不得用以下文本或任意代理值替换空键：

- Unknown
- Unassigned
- N A
- 零值标识符
- 人工生成客户、员工、商品、供应商、品类或承运商编号

需要展示未归属金额时，应通过独立的缺失标识或质量统计表达，不得写入伪造源键。

### 空值与外键的区别

允许为空的外键保持为空，不构成外键孤儿。

非空外键找不到父记录才构成外键孤儿，并适用 30 分钟处理宽限。

## 数据质量与异常处置

### 处置等级

质量结果分为关键失败和警告。

关键失败会隔离受影响记录并阻断受影响 Gold 数据产品发布。警告允许处理继续，但必须写入质量结果，并由数据 Steward 在规定期限内处置。

任何异常都不得通过静默改写源值解决。类型标准化、空白处理和布尔映射必须保留原值或可追溯元数据。

### 关键质量规则

以下规则失败时按关键失败处理：

- 所有源主键字段非空
- Silver 主键和组合主键唯一
- 非空外键在 30 分钟宽限后仍无法引用有效父记录
- `order_details.quantity` 大于零
- `order_details.unit_price` 大于等于零
- `order_details.discount` 位于零到一之间
- 已发货订单至少包含一条通过质量检查的订单明细
- `orders.freight` 大于等于零或为空
- `orders.shipped_date` 和 `orders.order_date` 都非空时，`shipped_date` 不早于 `order_date`
- `orders.required_date` 和 `orders.order_date` 都非空时，`required_date` 不早于 `order_date`
- `products.units_in_stock`、`products.units_on_order` 和 `products.reorder_level` 大于等于零或为空
- `products.discontinued` 只能取零或一
- DMS 操作类型合法且两种操作标识语义一致
- Full Load 操作类型为 `INSERT`
- `_dms_commit_ts` 可以解析为 UTC Timestamp
- `_dms_change_seq` 可以转换为 `DECIMAL 38,0`
- `_dms_source_schema` 为 `public`
- `_dms_source_table` 属于批准的 14 张表
- 数据代际和数据代际顺序属于批准配置
- 认证数据中的 `_rescued_data` 为空
- Restricted 字段未进入 DMS Parquet、Bronze、Silver 或 Gold
- 金额字段完成定点小数转换且没有溢出

### 警告规则

以下问题生成警告，不自动修改源值：

- 文本拼写、空白或格式异常
- `us_states` 中未被源外键引用的异常缩写
- `customer_demographics` 或 `customer_customer_demo` 没有记录
- 源日期、运费或库存字段的空值比例显著变化
- 当前商品目录价格与历史订单明细交易价格不同
- 当前名称或组织关系变化导致历史展示属性重述
- 客户或员工标识为空导致订单未归属
- 单次运行出现 `_rescued_data`
- DMS CDC 文件因时间阈值提前刷新而小于目标文件尺寸

样例源数据中的 Iowa 缩写 `IO` 必须按源值保留并生成警告，不得自动改写。

### 隔离与发布状态

隔离记录写入受控质量区域，并保留源业务键、规则标识、发现时间、来源文件和可追溯元数据。

每个 Gold 数据产品使用以下发布状态：

- `candidate`
- `certified`
- `blocked`

只有关键规则全部通过、增量对账成功并且数据新鲜度未超过最大允许延迟时，发布状态才能更新为 `certified`。

关键失败时，受影响数据产品状态更新为 `blocked`。失败运行不得覆盖最近一次已认证水位和已认证快照。

本文定义质量规则，不得据此声称检查已经执行或数据已经通过认证。

## 敏感数据与权限

### Restricted 字段

以下字段固定归类为 Restricted，并在 DMS 字段白名单阶段排除，不进入 S3 或 Databricks：

| 源表 | 排除字段 |
|---|---|
| `categories` | `picture` |
| `customers` | `contact_name`、`contact_title`、`address`、`postal_code`、`phone`、`fax` |
| `employees` | `title_of_courtesy`、`birth_date`、`address`、`city`、`region`、`postal_code`、`country`、`home_phone`、`extension`、`photo`、`notes`、`photo_path` |
| `orders` | `ship_name`、`ship_address`、`ship_postal_code` |
| `shippers` | `phone` |
| `suppliers` | `contact_name`、`contact_title`、`address`、`postal_code`、`phone`、`fax`、`homepage` |

任何 Restricted 字段进入 DMS 落地区或 Databricks 都按 Sev 1 安全事件处理。

### Confidential 字段

客户公司名、员工姓名、员工职位、员工入职日期、员工汇报关系、供应商公司名、承运商公司名，以及保留的城市、地区和国家字段固定归类为 Confidential。

Confidential 字段只能按已批准用途发布，并遵循 Unity Catalog 最小权限、血缘和审计规则。

`customer_company_name` 对产品 Owner 和数据 Steward 显示原值，对普通授权分析师显示基于 `customer_id` 的稳定别名。

`employee_name` 对产品 Owner 和数据 Steward 显示原值，对普通授权分析师显示基于 `employee_id` 的稳定别名。

列级保护统一使用 Unity Catalog Column Mask。项目不使用行级过滤表达组织权限，因为源 Schema 没有可验证的组织访问边界字段。

### 责任主体

| 责任 | 已确认主体 |
|---|---|
| 业务指标、SLA 和数据产品验收 | `grp_northwind_product_owners` |
| 数据定义、质量和分类 | `grp_northwind_stewards` |
| AWS、Databricks、DMS、存储和运行平台 | `grp_northwind_platform` |
| 安全策略、审计和敏感数据授权 | `grp_northwind_security` |

生产权限优先授予账户级 Group，禁止向个人直接授予生产数据权限。

## 明确禁止的业务推断

基于当前源 Schema，禁止生成或声明以下内容：

- 取消订单数量或取消销售额
- 退货数量、退款金额或净退货销售额
- 已付款、未付款或逾期付款状态
- 订单实际送达日期
- 准时送达率
- 实际运输时长
- 承运商最终配送绩效
- 具体货币代码或汇率换算结果
- 订单发生时的历史员工组织关系
- 基于员工区域关系推导的订单销售区域
- 源系统日终库存状态
- 源 Schema 未定义的统一订单状态

需要新增以上口径时，必须先增加可验证的数据来源，并完成源映射、指标、质量、治理和历史兼容性评审。

## 规则变更与失效

业务指标变更需要产品 Owner 和数据 Steward 批准。

源字段纳入或排除变更需要产品 Owner、数据 Steward 和安全 Owner 批准。

SLA、保留期、成本和平台运行规则变更需要产品 Owner 与平台 Owner 批准。

源 Schema 变更必须先更新注册结构事实文件；固定上游脚本发生对应变化时，还必须更新其来源版本和校验值。随后完成 DMS 映射、显式 Schema、质量规则、数据字典、权限和受影响数据产品的影响评估。

规则变更必须记录生效日期、影响范围、回补范围和旧规则失效状态。未完成确认前，现有已确认规则继续有效。

当前版本不存在开放业务规则。
