<!--
文件用途：说明 Northwind 源系统的身份、职责、数据范围、业务域、键关系、更新方式、抽取边界和已知限制，回答数据从哪里来以及源数据能够证明什么。
维护责任：由用户维护并确认。源表、字段、数据类型、主键和外键必须与 source-schema/northwind-schema.sql 保持一致。Agent 可以读取、引用和检查冲突，不得自行修改源事实或描述未经验证的运行状态。
事实边界：源结构事实仅来自 source-schema/northwind-schema.sql；样例数据验收事实仅来自 Workspace 根目录下固定的 upstream/northwind.sql。AWS DMS、S3 和 Databricks 相关内容属于已确认项目架构与抽取约束，不属于 Northwind 源 Schema 字段。
状态边界：本文定义设计与运行要求，不代表 Amazon RDS、AWS DMS、Amazon S3 或 Databricks 资源已经创建、连接、运行或通过验收。
内容边界：不得记录密码、连接串、令牌、密钥、真实资源编号、真实个人联系方式、未经确认的源字段或虚构的运行结果。
-->

# 源系统说明

## 文档定位

本文定义 Northwind 销售分析项目的源系统边界，是后续摄取、建模、质量、治理和数据产品设计判断数据来源的权威输入。

本文内容按以下类别解释：

| 类别 | 定义 |
|---|---|
| 源结构事实 | 直接来自注册结构事实文件的表、字段、数据类型、主键和外键 |
| 样例验收事实 | 从固定上游样例文件独立计算出的行数、日期范围、异常特征和金额基线 |
| 已确认抽取决定 | 已在项目需求和架构文件中确认的 RDS、DMS、S3、字段白名单和 CDC 处理规则 |
| 部署运行变量 | 从真实环境读取的账户编号、端点、ARN、Workspace 编号、密钥标识和通知目标编号 |
| 运行状态 | 连接、任务、文件、流水线和质量检查是否真实运行及通过，只能由环境证据确认 |

本文不替代注册结构事实文件。本文与该文件发生冲突时，以其中可验证的结构事实为准，并通过正式变更流程同步修正文档和下游设计。

## 系统身份与职责

### 系统身份

| 项目 | 已确认内容 |
|---|---|
| 源系统名称 | Northwind |
| 数据库服务 | Amazon RDS for PostgreSQL |
| AWS 区域 | `ap-northeast-1` |
| 数据库 Schema | `public` |
| 注册结构事实文件 | `source-schema/northwind-schema.sql` |
| 结构文件校验 | UTF-8；214 行；6617 字节；SHA256 `9857e1eec3687b47e6b4c55a087f77d7a272ff1f991e97bb31271ea30e7c1f9a` |
| 固定上游审计与样例文件 | Workspace 根目录下的 `upstream/northwind.sql` |
| 上游文件校验 | UTF-8；3912 行；349810 字节；SHA256 `0ee30c01ba282f7194f38bf7f99cd6be0470b7ee5f67d0f7ca41fb058d735e0c` |
| 源数据形态 | PostgreSQL 关系表 |
| 生产抽取形态 | Full Load 加持续 CDC |
| 非生产抽取形态 | 按需启动，测试完成后停止 |

两份文件不要求内容相同。注册结构事实文件必须能够从固定上游脚本确定性再生成，并在表、字段、数据类型、主键和外键上保持结构一致。结构文件校验值变化时必须重新核对全部结构依赖；上游文件校验值变化时还必须重新生成结构文件和全部样例验收基线。

### 业务职责

Northwind 为本项目提供以下业务事实和当前状态数据：

- 客户及客户类型
- 员工及汇报关系
- 员工与销售区域关系
- 商品、品类、供应商和当前库存属性
- 订单及订单商品明细
- 承运商和订单发货信息
- 大区、销售区域和美国州字典

源系统负责保存源业务记录。Databricks 负责摄取副本、版本合并、质量检查、指标计算、治理发布和运行审计。

源系统不负责提供 Databricks 发布状态、DMS 操作元数据、文件路径、摄取时间、质量结果、认证水位或数据产品指标。

### 项目内责任主体

| 责任 | 已确认主体 |
|---|---|
| 业务范围、指标和数据产品验收 | `grp_northwind_product_owners` |
| 源定义、数据质量、分类和异常判定 | `grp_northwind_stewards` |
| RDS 连通、DMS、S3、Databricks 平台和恢复 | `grp_northwind_platform` |
| DMS 映射、Pipeline、模型和质量实现 | `grp_northwind_engineering` |
| 安全策略、审计和敏感数据授权 | `grp_northwind_security` |
| 经批准的分析使用 | `grp_northwind_analysts` |

责任主体均为账户级 Group。实际值班人员、审批人和业务联系人从组织受控目录及事件管理系统读取，不在本文记录个人信息。

### 环境边界

生产环境连接生产 RDS。开发和测试环境只能连接隔离的非生产 RDS 或经过批准的脱敏副本。

每个环境使用独立 AWS 账户、独立 Databricks Workspace、独立 Catalog、独立 DMS 落地 Bucket、独立 Unity Catalog 托管存储 Bucket、独立审计 Bucket、独立 KMS Key 和独立运行身份。

跨环境读取和写入默认拒绝。生产源数据不得直接复制到开发环境，除非脱敏方案、安全审批和审计要求全部满足。

### Agent 边界

Agent 不连接 RDS、AWS 或 Databricks，不执行 SQL、DMS 任务、Pipeline、Notebook、Job 或部署命令，不读取真实凭证，不修改源 Schema 和源数据。

Agent 生成的架构、配置、代码和检查均为人工评审提案。真实部署状态和运行结果必须由环境证据确认。

## 数据范围

### 源结构基线

当前源结构包含 14 张表、92 个字段、14 个主键和 13 个外键。

| 项目 | 源事实 |
|---|---:|
| 数据表 | 14 |
| 字段 | 92 |
| 主键 | 14 |
| 外键 | 13 |
| 样例初始化数据 | 3362 行 |
| 视图 | 0 |
| 函数 | 0 |
| 存储过程 | 0 |
| 触发器 | 0 |
| 序列 | 0 |
| 显式普通索引 | 0 |

所有 14 张表都具有主键。源文件没有定义身份列或序列，目标平台必须完整保留源主键值，不得用平台生成键替代源业务键。

样例初始化数据只用于理解源结构、验证映射、构造非生产检查和建立对账基线。样例数据不得用于推断生产数据量、峰值、增长率、写入频率、吞吐、恢复能力、SLA 或成本。

### 源表与摄取范围

| 源表 | 源字段数 | 批准摄取字段数 | 源端排除字段数 | 样例行数 |
|---|---:|---:|---:|---:|
| `categories` | 4 | 3 | 1 | 8 |
| `customer_customer_demo` | 2 | 2 | 0 | 0 |
| `customer_demographics` | 2 | 2 | 0 | 0 |
| `customers` | 11 | 5 | 6 | 91 |
| `employees` | 18 | 6 | 12 | 9 |
| `employee_territories` | 2 | 2 | 0 | 49 |
| `order_details` | 5 | 5 | 0 | 2155 |
| `orders` | 14 | 11 | 3 | 830 |
| `products` | 10 | 10 | 0 | 77 |
| `region` | 2 | 2 | 0 | 4 |
| `shippers` | 3 | 2 | 1 | 6 |
| `suppliers` | 12 | 5 | 7 | 29 |
| `territories` | 3 | 3 | 0 | 53 |
| `us_states` | 4 | 4 | 0 | 51 |
| 合计 | 92 | 62 | 30 | 3362 |

DMS 使用精确表清单。禁止使用 Schema 通配符自动纳入新表。

新增表必须先更新注册结构事实文件；固定上游脚本发生对应变化时，还必须更新其来源版本和校验值。随后同步更新项目需求、本文、DMS 映射、Auto Loader 显式 Schema、Silver 类型转换、质量规则、权限、数据字典、数据产品和发布计划。

### 批准摄取字段

DMS 只摄取以下 62 个源字段：

| 源表 | 批准摄取字段 |
|---|---|
| `categories` | `category_id`、`category_name`、`description` |
| `customer_customer_demo` | `customer_id`、`customer_type_id` |
| `customer_demographics` | `customer_type_id`、`customer_desc` |
| `customers` | `customer_id`、`company_name`、`city`、`region`、`country` |
| `employees` | `employee_id`、`last_name`、`first_name`、`title`、`hire_date`、`reports_to` |
| `employee_territories` | `employee_id`、`territory_id` |
| `order_details` | `order_id`、`product_id`、`unit_price`、`quantity`、`discount` |
| `orders` | `order_id`、`customer_id`、`employee_id`、`order_date`、`required_date`、`shipped_date`、`ship_via`、`freight`、`ship_city`、`ship_region`、`ship_country` |
| `products` | `product_id`、`product_name`、`supplier_id`、`category_id`、`quantity_per_unit`、`unit_price`、`units_in_stock`、`units_on_order`、`reorder_level`、`discontinued` |
| `region` | `region_id`、`region_description` |
| `shippers` | `shipper_id`、`company_name` |
| `suppliers` | `supplier_id`、`company_name`、`city`、`region`、`country` |
| `territories` | `territory_id`、`territory_description`、`region_id` |
| `us_states` | `state_id`、`state_name`、`state_abbr`、`state_region` |

未列出的源字段不得进入 DMS Parquet、Landing、Bronze、Silver、Gold 或 Ops。

### 源端排除字段

以下 30 个字段固定归类为 Restricted，并在 DMS 字段白名单阶段排除：

| 源表 | 源端排除字段 | 数量 |
|---|---|---:|
| `categories` | `picture` | 1 |
| `customers` | `contact_name`、`contact_title`、`address`、`postal_code`、`phone`、`fax` | 6 |
| `employees` | `title_of_courtesy`、`birth_date`、`address`、`city`、`region`、`postal_code`、`country`、`home_phone`、`extension`、`photo`、`notes`、`photo_path` | 12 |
| `orders` | `ship_name`、`ship_address`、`ship_postal_code` | 3 |
| `shippers` | `phone` | 1 |
| `suppliers` | `contact_name`、`contact_title`、`address`、`postal_code`、`phone`、`fax`、`homepage` | 7 |
| 合计 | 固定排除字段 | 30 |

任何 Restricted 字段进入 DMS 落地区或 Databricks 都属于 Sev 1 安全事件。受影响 Pipeline 和 Gold 发布必须停止，产品状态更新为 `blocked`，并由安全 Owner 主导范围确认、隔离、清理和恢复验收。

注册结构事实文件只包含结构 DDL。固定上游脚本可以记录原始样例内容，因此属于受控审计与验收资产；它不注册为 Agent 上下文，也不得发送给模型、作为不受限日志输入或作为数据产品来源。

### 源数据类型

源 Schema 使用以下类型族：

| 类型族 | 字段数 | 主要用途 |
|---|---:|---|
| `character varying` | 55 | 名称、标识、地址片段、地区和描述 |
| `smallint` | 21 | 主键、外键、数量和库存数值 |
| `date` | 5 | 订单日期、要求日期、发货日期、出生日期和入职日期 |
| `text` | 4 | 描述、备注和主页文本 |
| `real` | 4 | 交易单价、商品当前单价、折扣和运费 |
| `bytea` | 2 | 品类图片和员工照片 |
| `integer` | 1 | 商品停售状态 |

`birth_date`、`notes`、`homepage` 和两个 `bytea` 字段均已按字段白名单排除。

保留的 `categories.description` 和 `customer_demographics.customer_desc` 没有源端长度上限，DMS 对这两个字段使用 Full LOB。LOB 截断属于抽取失败，不允许静默截断。

### 样例数据基线

| 项目 | 当前样例值 |
|---|---:|
| 订单 | 830 |
| 已发货订单 | 809 |
| 未发货订单 | 21 |
| 订单明细 | 2155 |
| 订单商品总数量 | 51317 |
| 晚于要求日期发货的订单 | 37 |
| 商品 | 77 |
| 停售商品 | 10 |
| 客户 | 91 |
| 员工 | 9 |
| 供应商 | 29 |
| 承运商 | 6 |

这 37 张订单只验证 `shipped_date` 晚于 `required_date` 的发货处理代理状态，不代表实际延迟送达。

固定上游样例文件变化后必须验证来源版本和校验值，并重新生成样例行数、订单范围、日期范围、金额基线和异常基线。旧基线不得继续用于验收。

## 表与业务域

### 业务域总览

| 业务域 | 源表 | 主要职责 |
|---|---|---|
| 销售交易 | `orders`、`order_details` | 保存订单头、订单日期、发货日期、运费和订单商品交易明细 |
| 客户 | `customers`、`customer_demographics`、`customer_customer_demo` | 保存当前客户属性、客户类型定义和客户到类型关系 |
| 商品与供应 | `products`、`categories`、`suppliers` | 保存当前商品、品类、供应商、当前价格和库存属性 |
| 员工与销售区域 | `employees`、`employee_territories`、`territories`、`region` | 保存当前员工、汇报关系、员工区域映射、销售区域和大区 |
| 配送 | `shippers`、`orders` | 保存承运商和订单发货相关字段 |
| 参考字典 | `us_states` | 保存美国州名称、缩写和区域文本 |

### 销售交易域

#### `orders`

每行代表一张订单，业务粒度为 `order_id`。

可用于以下事实：

- 客户归属
- 员工归属
- 下单日期
- 要求日期
- 发货日期
- 承运商归属
- 订单粒度运费
- 获准保留的收货城市、地区和国家

`orders.freight` 位于订单粒度，只能在订单粒度累计一次。商品、品类和员工销售指标不得重复累计或分摊运费。

`orders.shipped_date` 可为空。认证销售只统计 `shipped_date` 非空的订单，销售归属日期直接使用 `shipped_date`。

`orders.order_date` 表示订单创建日期，不承担认证销售归属。

`orders.required_date` 只用于已确认的发货处理代理指标。

#### `order_details`

每行代表一张订单中的一个商品，业务粒度为 `order_id` 加 `product_id`。

`order_details.unit_price` 是订单明细中的交易价格，是历史销售金额计算的唯一单价来源。

`order_details.quantity` 是该订单商品数量。

`order_details.discount` 是零到一之间的折扣比例。

销售金额规则由已确认业务与数据规则定义。源端 `real` 值进入目标层后必须先转换为定点小数，再使用 `HALF_UP` 四位小数规则计算。

### 客户域

#### `customers`

每行代表一个当前客户，业务粒度为 `customer_id`。

获准摄取的属性包括公司名、城市、地区和国家。联系人、职位、详细地址、邮政编码、电话和传真在源端排除。

客户属性没有有效起止日期。历史销售刷新后可以显示客户当前属性，客户源标识归属保持不变。

订单中的 `customer_id` 可为空。合法空客户订单保留源空值，不创建未知客户或其他伪造维度成员。

#### `customer_demographics`

每行代表一个客户类型，业务粒度为 `customer_type_id`。

#### `customer_customer_demo`

每行代表一个客户与客户类型的关系，业务粒度为 `customer_id` 加 `customer_type_id`。

当前样例中 `customer_demographics` 和 `customer_customer_demo` 均无数据。两张表仍属于正式摄取范围，不能因样例为空而删除结构或跳过 CDC 设计。

### 商品与供应域

#### `products`

每行代表一个当前商品，业务粒度为 `product_id`。

该表保存商品名称、当前供应商、当前品类、包装描述、当前单价、当前库存、在途数量、补货阈值和停售状态。

`products.unit_price` 表示商品当前价格，只能作为当前商品属性使用。历史交易金额不得用该字段替换 `order_details.unit_price`。

`units_in_stock`、`units_on_order` 和 `reorder_level` 表示源系统被观察时的当前状态。源 Schema 没有库存快照日期和库存变更流水，不能据此生成历史日终库存。

`discontinued` 使用整数，源 Schema 没有布尔检查约束。目标层只把合法零值和一值解释为已确认状态，其他值进入质量处置。

#### `categories`

每行代表一个当前商品品类，业务粒度为 `category_id`。

品类名称和描述获准摄取。图片字段在源端排除。

#### `suppliers`

每行代表一个当前供应商，业务粒度为 `supplier_id`。

获准摄取供应商公司名、城市、地区和国家。联系人、职位、详细地址、邮政编码、电话、传真和主页在源端排除。

商品到供应商的归属来自 `products.supplier_id`。源 Schema 没有供应关系有效期。

### 员工与销售区域域

#### `employees`

每行代表一个当前员工，业务粒度为 `employee_id`。

获准摄取员工姓名、职位、入职日期和上级员工标识。其他个人信息、联系信息、备注、照片和图片路径在源端排除。

`reports_to` 建立员工自关联层级。空值表示没有可用上级记录，当前样例中的最高层员工使用空值。

员工职位、姓名和汇报关系没有有效期。历史订单只按 `orders.employee_id` 保持稳定员工标识归属，不能重建订单发生时的历史组织关系。

#### `employee_territories`

每行代表一个员工与销售区域的关系，业务粒度为 `employee_id` 加 `territory_id`。

该表形成员工到销售区域的多对多关系。

`orders` 没有 `territory_id`。员工订单不得依据 `employee_territories` 分摊到销售区域，也不得生成订单级销售区域归属。

#### `territories`

每行代表一个销售区域，业务粒度为 `territory_id`。

每个销售区域必须引用一个大区。

#### `region`

每行代表一个大区，业务粒度为 `region_id`。

### 配送域

#### `shippers`

每行代表一个承运商，业务粒度为 `shipper_id`。

公司名获准摄取，电话在源端排除。

`orders.ship_via` 建立订单到承运商的可空关系。

源系统没有实际送达日期、签收状态、运输轨迹或承运商服务事件。配送产品只能发布发货处理代理指标，不能声明实际运输时长、准时送达率或承运商最终配送绩效。

### 参考字典域

#### `us_states`

每行代表一条美国州字典记录，业务粒度为 `state_id`。

该表没有被其他源表通过外键引用。认证数据产品不得使用文本相似或缩写匹配把客户、供应商或订单地区自动映射到 `us_states`。

当前样例中 Iowa 的州缩写为 `IO`。目标层保留源值并生成质量警告，不自动改写。

## 主键与关联关系

### 主键清单

| 源表 | 主键 | 键类型 |
|---|---|---|
| `categories` | `category_id` | 单列主键 |
| `customer_customer_demo` | `customer_id` 加 `customer_type_id` | 组合主键 |
| `customer_demographics` | `customer_type_id` | 单列主键 |
| `customers` | `customer_id` | 单列主键 |
| `employees` | `employee_id` | 单列主键 |
| `employee_territories` | `employee_id` 加 `territory_id` | 组合主键 |
| `order_details` | `order_id` 加 `product_id` | 组合主键 |
| `orders` | `order_id` | 单列主键 |
| `products` | `product_id` | 单列主键 |
| `region` | `region_id` | 单列主键 |
| `shippers` | `shipper_id` | 单列主键 |
| `suppliers` | `supplier_id` | 单列主键 |
| `territories` | `territory_id` | 单列主键 |
| `us_states` | `state_id` | 单列主键 |

所有主键字段在源 DDL 中均为非空。Full Load、CDC、Silver 当前状态和 Gold 粒度检查必须使用完整源主键。

组合主键不得拆分为单列去重。`order_details` 的唯一版本必须按 `order_id` 加 `product_id` 识别。

### 外键清单

| 子表字段 | 父表字段 | 源端可空 | 业务含义 |
|---|---|---|---|
| `orders.customer_id` | `customers.customer_id` | 是 | 订单客户 |
| `orders.employee_id` | `employees.employee_id` | 是 | 订单员工 |
| `orders.ship_via` | `shippers.shipper_id` | 是 | 订单承运商 |
| `order_details.order_id` | `orders.order_id` | 否 | 明细所属订单 |
| `order_details.product_id` | `products.product_id` | 否 | 明细商品 |
| `products.category_id` | `categories.category_id` | 是 | 商品当前品类 |
| `products.supplier_id` | `suppliers.supplier_id` | 是 | 商品当前供应商 |
| `territories.region_id` | `region.region_id` | 否 | 销售区域所属大区 |
| `employee_territories.employee_id` | `employees.employee_id` | 否 | 区域关系员工 |
| `employee_territories.territory_id` | `territories.territory_id` | 否 | 区域关系销售区域 |
| `customer_customer_demo.customer_id` | `customers.customer_id` | 否 | 客户类型关系客户 |
| `customer_customer_demo.customer_type_id` | `customer_demographics.customer_type_id` | 否 | 客户类型关系类型 |
| `employees.reports_to` | `employees.employee_id` | 是 | 员工上级 |

源 DDL 没有声明级联更新或级联删除，数据库采用 PostgreSQL 默认约束行为。

源 DDL 没有为外键字段显式创建普通索引。主键约束会创建对应唯一索引，外键查询性能不能由源文件推断。

### 关系边界

可依赖关系只来自源 DDL 的 13 条外键。名称相似、文本相同或业务常识不能建立新的认证关系。

以下边界必须保持：

- `us_states` 与地址字段之间没有源外键
- `orders` 与 `territories` 之间没有源外键
- `orders` 与 `region` 之间没有源外键
- 订单明细价格与商品当前价格之间没有历史一致性要求
- 客户当前属性与订单发生时属性之间没有历史版本关系
- 员工当前组织关系与订单发生时组织关系之间没有历史版本关系

外键列合法空值必须保留。下游不得创建未知客户、未知员工、未知品类、未知供应商或未知承运商等伪造维度成员。

非空外键在 CDC 乱序期间允许 30 分钟处理宽限。宽限结束后仍未找到父记录的行进入隔离，并阻断受影响 Gold 产品认证发布。

## 更新与抽取方式

### 源更新特征

注册结构事实文件和固定上游样例文件都没有定义生产环境的固定业务写入频率、批次窗口、峰值、增量比例或源端服务等级。

项目对源写入采用事件驱动假设。生产环境通过持续 CDC 捕获已提交的行级变更，不要求源应用按固定批次更新。

源表没有统一的创建时间、更新时间、版本号或摄取时间字段。`order_date`、`required_date`、`shipped_date` 和 `hire_date` 等字段只表达各自业务语义，不能作为通用 CDC 排序字段。

所有源日期保持 PostgreSQL `date` 语义，不进行时区换算。DMS 提交时间和 Databricks 摄取时间使用 UTC，只承担传输排序、审计和新鲜度计算。

### 基准抽取链路

基准链路固定为：

`Amazon RDS for PostgreSQL → AWS DMS Serverless → Amazon S3 Parquet → Unity Catalog External Volume → Auto Loader → Bronze Delta → Silver Delta → Gold Delta`

DMS 负责 Full Load 和 CDC 文件落地。Databricks 使用 Auto Loader Managed File Events 增量读取 S3 Parquet。

项目不采用 Preview、Beta、实验性或私有预览能力。

### DMS 任务基线

| 项目 | 已确认值 |
|---|---|
| DMS 形态 | AWS DMS Serverless |
| 迁移模式 | Full Load and CDC |
| 生产运行方式 | 持续 CDC |
| 非生产运行方式 | 按需启动，测试完成后停止 |
| 最小容量 | 1 DCU |
| 最大容量 | 16 DCU |
| Multi AZ | 启用 |
| 网络 | 私有子网，至少跨两个可用区 |
| 公网访问 | 禁止 |
| 源连接端口 | PostgreSQL 5432 |
| 源 TLS | `verify-full` |
| 凭证来源 | AWS Secrets Manager 专用 Secret |
| PostgreSQL 解码插件 | `test_decoding` |
| DDL 自动捕获 | 关闭 |
| CloudWatch 日志 | 启用 |
| LOB 模式 | Full LOB |
| LOB Chunk | 64 KB |
| LOB 截断处置 | 发现截断即失败 |

真实 RDS 端点、数据库名、证书 ARN、Secret 标识、IAM Role ARN 和账户编号属于部署运行变量，不得写入本文或代码仓库明文配置。

### PostgreSQL CDC 前置条件

生产 CDC 必须满足以下条件：

- RDS 参数组设置 `rds.logical_replication=1`
- 必要重启在受控维护窗口完成
- DMS 使用专用数据库角色 `dms_northwind_<environment>`
- DMS 角色只获得 `public` Schema 使用权、14 张批准表读取权、心跳 Schema 使用权和 CDC 所需复制权限
- 应用账号、个人账号和 RDS Master 账号不得作为长期 DMS 运行身份
- 项目使用一个活动逻辑复制槽并额外预留一个备用槽位
- `max_replication_slots` 至少比其他已用槽位数量多两个
- `max_wal_senders` 至少比其他已用发送进程数量多两个
- WAL Heartbeat 频率固定为 5 分钟
- WAL Heartbeat Schema 固定为 `dms_heartbeat`
- 持续监控复制槽磁盘使用量、WAL 保留量、DMS 延迟和 RDS 可用存储
- 活动 CDC 期间禁止修改主键结构
- 业务删除使用行级 DELETE
- 禁止依赖 TRUNCATE 表达业务删除

源 DDL 变更必须先更新注册结构事实文件和全部下游约束；固定上游脚本发生对应变化时同步更新其来源版本和校验值，再进入部署评审。

### Full Load

初始数据代际固定为 `v1`。Full Load 与持续 CDC 使用同一 DMS Serverless 配置，不建立独立长期全量任务。

Full Load 覆盖 14 张批准表和 62 个批准字段。

Full Load 记录的标准操作类型为 `INSERT`。Full Load 的提交时间使用任务启动时间，只用于平台排序和审计，不承担业务事件时间语义。

Full Load 文件之间以及 Full Load 与 CDC 文件之间不得依赖对象名称顺序。Silver 按源业务键、数据代际和确定性变更顺序形成当前状态。

重新执行 Full Load、更换无法续接原复制槽的 DMS 任务、更换源数据库或发生不可修复数据污染时，必须创建新的数据代际。

新数据代际完成全量对账、CDC 连续性验证和质量门禁后，才能切换 Silver 和 Gold 认证引用。

### CDC 操作

CDC 只接受以下标准操作类型：

- `INSERT`
- `UPDATE`
- `DELETE`

传输层操作标识只接受 `I`、`U` 和 `D`，并且必须与标准操作类型语义一致。

操作类型缺失、非法或相互矛盾时，记录进入隔离，受影响数据产品停止认证发布。

Bronze 保留 DELETE 事件。Silver 收到有效 DELETE 后移除对应源业务键的当前记录。Gold 在后续刷新中移除该记录产生的当前认证结果。

删除后重插、重复文件、任务重试和乱序事件必须得到确定且幂等的 Silver 当前状态。

### DMS 传输元数据

以下字段由 DMS 或部署参数提供，不属于 Northwind 源 Schema：

| 元数据 | 用途 |
|---|---|
| `_dms_transport_operation` | 校验传输层操作标识 |
| `_dms_operation` | 标准化操作类型 |
| `_dms_commit_ts` | 源提交时间或 Full Load 任务启动时间 |
| `_dms_change_seq` | 任务级事件顺序 |
| `_dms_stream_position` | PostgreSQL 日志流位置 |
| `_dms_source_schema` | 源 Schema |
| `_dms_source_table` | 源表 |
| `_dataset_generation` | 区分受控全量数据代际 |

Databricks 另外保留摄取时间、源文件路径、文件修改时间、Pipeline Update 标识、加载阶段、数据代际顺序和 `_rescued_data`。

这些元数据只用于审计、排序、去重、删除、恢复和新鲜度计算。它们不得替代 `order_date`、`required_date` 或 `shipped_date` 等业务日期。

同一源业务键的版本优先级固定使用数据代际顺序、CDC 优先级、变更序列、提交时间、日志位置、摄取时间和源文件路径形成确定顺序。

`_dms_change_seq` 必须转换为 `DECIMAL 38,0` 后参与排序。无法转换的记录进入隔离。

### S3 输出约定

| 参数 | 已确认值 |
|---|---|
| 文件格式 | Parquet |
| Parquet 版本 | 2.0 |
| 统计信息 | 启用 |
| 加密 | SSE KMS |
| Glue Catalog 自动生成 | 关闭 |
| 跨表事务保留 | 关闭 |
| 日期分区 | 启用 |
| 日期分区粒度 | UTC 小时 |
| CDC 最大批次间隔 | 300 秒 |
| CDC 目标最小文件大小 | 32000 KB |
| 目标最大文件大小 | 131072 KB |
| 根目录 | `landing/northwind/<dataset_generation>` |

每张表使用独立目录：

`landing/northwind/<dataset_generation>/public/<table>`

Full Load 文件位于表根目录。CDC 文件位于表目录下的 UTC 年、月、日和小时目录。

DMS 落地对象采用追加写入，不覆盖已有对象。下游不得从文件名推断业务日期、源主键或操作顺序。

跨表事务顺序不保留。下游只能按每张表的源主键、数据代际、变更序列、提交时间和日志位置执行确定性合并。

### 抽取频率与下游触发

生产 DMS 持续运行 CDC。DMS 最大批次间隔固定为 300 秒。

Databricks 使用 File Arrival Trigger，最小触发间隔为 5 分钟，文件静默等待为 60 秒。

端到端数据新鲜度目标为源提交后 P95 15 分钟内进入 Gold，最大允许延迟为 30 分钟。该目标属于项目运行要求，不能从源 SQL 样例推断。

开发和测试环境按需启动 DMS，测试完成后停止，避免长期空闲成本。

### Schema 变更

DMS DDL 自动捕获固定关闭。Schema 变化不得自动进入 S3、Bronze、Silver 或 Gold。

任何源表、字段、数据类型、主键或外键变更都必须执行以下流程：

1. 更新注册结构事实文件
2. 固定上游脚本发生对应变化时，更新其来源版本和校验值，并验证结构文件可确定性再生成
3. 更新本文和项目需求
4. 完成业务、数据质量、安全和兼容性影响评估
5. 更新 DMS 精确表映射和字段白名单
6. 更新 Auto Loader 显式 Schema
7. 更新 Silver 类型转换和 CDC 键规则
8. 更新质量规则、数据字典、权限和标签
9. 更新受影响数据产品和对账规则
9. 在开发和测试环境完成双轨验证
10. 通过生产发布门禁后进入生产

新增字段默认不获准摄取。未经批准的新字段进入 `_rescued_data`，不得进入认证 Gold。

破坏性 Schema 变化优先采用新增列或新增表并行验证，再通过受控切换完成迁移。

## 已知限制

### 生产规模未知

注册结构事实文件只提供源结构；固定上游脚本只提供非生产样例数据。两份文件都没有生产行数、每日增量、峰值并发、增长率、事务大小、WAL 产生速率、源端保留策略或业务写入分布。

DMS 容量、Auto Loader 吞吐、Databricks 运行时长和成本必须以真实监控数据评审。样例数据不得作为生产容量基线。

### 缺少统一源审计字段

源表没有统一的创建时间、更新时间、版本号、删除标识或变更序列。

CDC 排序依赖 DMS 传输元数据和数据代际。DMS 元数据缺失或不合法时，不能用业务日期或文件名替代确定性顺序。

### 日期精度有限

源日期字段均为 `date`，没有时分秒和时区。

无法从源字段确定同一天内的业务事件先后顺序。运行审计使用 UTC，源日期保持原始日历值。

### 当前状态缺少历史有效期

客户、员工、商品、品类、供应商、承运商、员工区域关系和客户类型关系没有有效起止日期。

历史销售刷新后可以显示最新当前属性。源标识归属保持稳定，无法重建订单发生时的历史名称、组织关系、品类归属、供应商归属或承运商名称。

### 业务语义缺口

源 Schema 没有以下字段或可验证事实：

- 订单统一状态
- 取消状态和取消原因
- 付款状态和付款日期
- 退货状态和退货数量
- 退款状态和退款金额
- 货币代码
- 汇率
- 实际送达日期
- 签收状态
- 运输轨迹
- 订单发生时的历史员工组织关系
- 订单级销售区域
- 历史日终库存

数据产品不得生成或声明取消销售额、退货销售额、退款金额、付款状态、具体币种、汇率换算结果、准时送达率、实际运输时长、承运商最终配送绩效或订单级销售区域。

### 销售与配送解释限制

认证销售只统计 `shipped_date` 非空订单，销售归属日期使用 `shipped_date`。

`shipped_date` 表达源中可用的发货日期。它不能证明订单已经送达。

`required_date` 仅用于发货处理代理指标。`shipped_date` 晚于 `required_date` 只表示该代理状态，不能解释为实际延迟送达。

配送产品同时覆盖已发货和未发货订单，但只能描述订单创建、要求日期、发货日期和开放订单积压。

### 金额与数值限制

交易单价、商品当前单价、折扣和运费使用 PostgreSQL `real`，存在浮点表示误差。

目标层必须先转换为定点小数，再计算订单行毛额、折扣金额、净销售额和订单运费。

销售金额使用 `order_details.unit_price`。`products.unit_price` 只表示当前商品价格。

源 Schema 没有货币代码。所有金额只标记为源系统金额，不声明为美元或其他具体币种，不做汇率换算。

`freight` 位于订单粒度。按订单明细连接时不得重复累计。

### 约束覆盖有限

源 DDL 没有定义业务检查约束，数据库本身不会限制以下异常：

- 负数量
- 负交易单价
- 折扣小于零或大于一
- 负运费
- 负库存
- 非零值和一值的停售状态
- 异常日期顺序

目标平台必须按数据质量文件执行范围、日期、主键、外键和金额检查。

源 DDL 没有显式普通索引、触发器、存储过程或序列。任何性能、自动编号或源端业务逻辑都不能从该文件推断。

### 可空关系

订单客户、订单员工、订单承运商、商品品类、商品供应商和员工上级均可为空。

合法空值必须保留。下游不得填充虚假标识或伪造维度成员。

非空孤儿关系在 CDC 乱序宽限结束后进入隔离。

### 关系推断限制

员工到销售区域是多对多关系，订单没有销售区域字段。员工销售不能分摊到区域。

`us_states` 没有源外键。州字典不能通过文本匹配自动连接客户、供应商或订单地址。

当前属性表没有历史版本。名称和描述变化不能用于推断历史维度状态。

### 样例数据异常

当前样例中存在以下已知特征：

- Iowa 的州缩写记录为 `IO`
- 部分员工文本包含反斜杠加字母 n 的字面内容
- 员工图片路径目录文本存在拼写问题
- 多个员工图片路径指向相同文件名
- 品类图片和员工照片样例内容为空二进制值
- 客户类型和客户到类型关系样例为空

Iowa 缩写按源值保留并生成质量警告。其他涉及 Restricted 字段的异常只在受控源资产中保留，不进入 DMS 落地区或 Databricks。

样例异常不得在未经批准的情况下自动改写源值。

### 源文件执行风险

固定上游脚本 `upstream/northwind.sql` 包含删除同名表、创建表、插入样例数据和添加约束的完整脚本。注册结构事实文件只保留建表和约束 DDL。

固定上游脚本具有覆盖性，不得直接对生产数据库执行。注册结构事实文件也只是 Agent 的只读结构输入，不是生产在线迁移脚本。

固定上游脚本中的插入语句没有显式字段列表，依赖建表字段顺序。源结构发生变化后，旧插入语句可能失效或写入错误位置。

固定上游脚本没有统一事务包裹。执行中途失败可能留下部分对象或部分数据。

### 抽取边界

DMS 只读取 `public` Schema 中明确批准的 14 张表和 62 个字段。

新表、新字段、Restricted 字段、未批准 Schema 和 DDL 变化不会自动进入认证链路。

跨表事务顺序不保留。业务一致性依赖源主键、外键宽限、表内 CDC 顺序、质量门禁和产品对账。

业务删除必须通过行级 DELETE 捕获。TRUNCATE 不作为业务删除语义。

二进制图片字段全部排除。保留文本 LOB 使用 Full LOB，任何截断都阻断抽取验收。

### 安全与凭证边界

源连接使用私有网络、TLS `verify-full`、Secrets Manager 和专用最小权限角色。

本文及项目仓库不得保存数据库密码、连接串、Secret 值、真实 ARN、真实端点、真实账户编号或个人联系方式。

Restricted 字段值不得进入日志、告警正文、质量错误摘要、隔离摘要、Notebook 输出、工单附件或未经批准的导出副本。

### 状态边界

本文记录的表、字段和约束已经依据注册结构事实文件建立设计基线；样例特征已经依据固定上游样例文件建立验收基线。

本文记录的 DMS、S3、网络、权限、CDC 和下游参数是已确认项目要求。

任何真实环境连接成功、Full Load 完成、CDC 连续、Restricted 扫描通过、质量检查通过、SLA 达成或生产发布完成的结论，都必须由对应环境的运行证据确认。

## 变更控制

以下变化必须进入正式变更流程：

- 注册结构事实文件校验值变化
- 固定上游审计与样例文件校验值变化
- 源 Schema 名变化
- 新增或删除表
- 新增、删除、重命名或改变字段类型
- 主键或外键变化
- Restricted 字段分类变化
- DMS 表清单或字段白名单变化
- 逻辑复制配置变化
- Full Load 重建或数据代际切换
- 源区域、数据库实例或端点变化
- 业务指标开始依赖新的源事实

变更记录必须包含生效日期、原因、影响表、影响字段、数据产品影响、质量影响、安全影响、回补范围、旧规则失效状态和批准主体。

未经批准的源变化不得自动进入生产摄取。现有已确认规则继续有效，直到正式变更完成并通过发布门禁。
