-- AWS 零售销售 Mock 项目的 Bronze 逻辑 DDL，仅供设计与代码生成参考。

CREATE TABLE IF NOT EXISTS bronze.pos_sales_raw (
  business_date DATE NOT NULL COMMENT '门店业务日期',
  store_id STRING NOT NULL COMMENT '门店业务键',
  transaction_id STRING NOT NULL COMMENT 'POS 交易业务键',
  line_id STRING NOT NULL COMMENT '交易行业务键',
  product_id STRING NOT NULL COMMENT '商品业务键',
  customer_id STRING COMMENT '受控客户分析标识',
  quantity DECIMAL(18,3) NOT NULL COMMENT '销售数量',
  gross_amount DECIMAL(18,2) NOT NULL COMMENT '折扣前金额',
  discount_amount DECIMAL(18,2) NOT NULL COMMENT '折扣金额',
  net_amount DECIMAL(18,2) NOT NULL COMMENT '净金额',
  currency_code STRING NOT NULL COMMENT '源币种代码',
  sale_ts TIMESTAMP NOT NULL COMMENT 'UTC 销售时间',
  _ingest_ts TIMESTAMP NOT NULL COMMENT 'Databricks 摄取时间',
  _source_file STRING NOT NULL COMMENT '源文件路径',
  _rescued_data STRING COMMENT 'Auto Loader 隔离字段',
  source_record_hash STRING NOT NULL COMMENT '源记录稳定哈希'
)
USING DELTA
PARTITIONED BY (business_date)
COMMENT 'Mock POS 日批原始销售行';

CREATE TABLE IF NOT EXISTS bronze.customer_cdc_raw (
  customer_id STRING NOT NULL COMMENT '客户业务键',
  full_name STRING COMMENT '受限虚构姓名',
  email STRING COMMENT '受限虚构邮箱',
  phone STRING COMMENT '受限虚构手机号',
  address STRING COMMENT '受限虚构地址',
  loyalty_tier STRING COMMENT '会员等级',
  created_at TIMESTAMP COMMENT '源创建时间',
  updated_at TIMESTAMP COMMENT '源更新时间',
  _dms_op STRING NOT NULL COMMENT 'AWS DMS I、U、D 操作',
  _dms_commit_ts TIMESTAMP NOT NULL COMMENT 'AWS DMS 提交时间',
  _ingest_ts TIMESTAMP NOT NULL COMMENT 'Databricks 摄取时间',
  _source_file STRING NOT NULL COMMENT 'DMS 落地文件路径',
  _rescued_data STRING COMMENT 'Auto Loader 隔离字段'
)
USING DELTA
COMMENT 'Mock RDS customer full load 与 CDC 原始记录';

CREATE TABLE IF NOT EXISTS bronze.product_cdc_raw (
  product_id STRING NOT NULL COMMENT '商品业务键',
  sku STRING NOT NULL COMMENT '商品 SKU',
  product_name STRING NOT NULL COMMENT '商品名称',
  category_id STRING NOT NULL COMMENT '品类业务键',
  category_name STRING NOT NULL COMMENT '品类名称',
  brand STRING COMMENT '品牌',
  unit_price DECIMAL(18,2) NOT NULL COMMENT '当前源单价',
  active_flag BOOLEAN NOT NULL COMMENT '源有效标识',
  updated_at TIMESTAMP COMMENT '源更新时间',
  _dms_op STRING NOT NULL COMMENT 'AWS DMS I、U、D 操作',
  _dms_commit_ts TIMESTAMP NOT NULL COMMENT 'AWS DMS 提交时间',
  _ingest_ts TIMESTAMP NOT NULL COMMENT 'Databricks 摄取时间',
  _source_file STRING NOT NULL COMMENT 'DMS 落地文件路径',
  _rescued_data STRING COMMENT 'Auto Loader 隔离字段'
)
USING DELTA
COMMENT 'Mock RDS product full load 与 CDC 原始记录';

CREATE TABLE IF NOT EXISTS bronze.store_cdc_raw (
  store_id STRING NOT NULL COMMENT '门店业务键',
  store_name STRING NOT NULL COMMENT '门店名称',
  region_code STRING NOT NULL COMMENT '区域代码',
  timezone STRING NOT NULL COMMENT 'IANA 业务时区',
  opened_date DATE COMMENT '开业日期',
  active_flag BOOLEAN NOT NULL COMMENT '源有效标识',
  updated_at TIMESTAMP COMMENT '源更新时间',
  _dms_op STRING NOT NULL COMMENT 'AWS DMS I、U、D 操作',
  _dms_commit_ts TIMESTAMP NOT NULL COMMENT 'AWS DMS 提交时间',
  _ingest_ts TIMESTAMP NOT NULL COMMENT 'Databricks 摄取时间',
  _source_file STRING NOT NULL COMMENT 'DMS 落地文件路径',
  _rescued_data STRING COMMENT 'Auto Loader 隔离字段'
)
USING DELTA
COMMENT 'Mock RDS store full load 与 CDC 原始记录';

CREATE TABLE IF NOT EXISTS bronze.inventory_cdc_raw (
  store_id STRING NOT NULL COMMENT '门店业务键',
  product_id STRING NOT NULL COMMENT '商品业务键',
  on_hand_quantity DECIMAL(18,3) NOT NULL COMMENT '账面库存数量',
  reserved_quantity DECIMAL(18,3) NOT NULL COMMENT '预留库存数量',
  reorder_point DECIMAL(18,3) COMMENT '补货阈值',
  snapshot_ts TIMESTAMP NOT NULL COMMENT 'UTC 库存时点',
  updated_at TIMESTAMP COMMENT '源更新时间',
  _dms_op STRING NOT NULL COMMENT 'AWS DMS I、U、D 操作',
  _dms_commit_ts TIMESTAMP NOT NULL COMMENT 'AWS DMS 提交时间',
  _ingest_ts TIMESTAMP NOT NULL COMMENT 'Databricks 摄取时间',
  _source_file STRING NOT NULL COMMENT 'DMS 落地文件路径',
  _rescued_data STRING COMMENT 'Auto Loader 隔离字段'
)
USING DELTA
COMMENT 'Mock RDS inventory full load 与 CDC 原始记录';

CREATE TABLE IF NOT EXISTS bronze.ecommerce_events_raw (
  event_id STRING NOT NULL COMMENT 'Kinesis 幂等事件键',
  event_type STRING NOT NULL COMMENT '订单、支付或行为事件类型',
  event_ts TIMESTAMP NOT NULL COMMENT 'UTC 事件发生时间',
  order_id STRING COMMENT '订单业务键',
  order_line_id STRING COMMENT '订单行业务键',
  customer_id STRING COMMENT '受控客户分析标识',
  product_id STRING COMMENT '商品业务键',
  store_id STRING COMMENT '归属门店业务键',
  channel STRING NOT NULL COMMENT '销售或行为渠道',
  quantity DECIMAL(18,3) COMMENT '事件数量',
  gross_amount DECIMAL(18,2) COMMENT '事件折扣前金额',
  discount_amount DECIMAL(18,2) COMMENT '事件折扣金额',
  net_amount DECIMAL(18,2) COMMENT '事件净金额',
  currency_code STRING COMMENT '事件币种代码',
  payload STRING NOT NULL COMMENT '受控原始 JSON payload',
  kinesis_partition_key STRING NOT NULL COMMENT 'Kinesis 分区键',
  kinesis_sequence_number STRING NOT NULL COMMENT 'Kinesis 序列号',
  _ingest_ts TIMESTAMP NOT NULL COMMENT 'Databricks 摄取时间',
  _rescued_data STRING COMMENT '解析隔离字段'
)
USING DELTA
COMMENT 'Mock Kinesis 电商订单、支付和客户行为事件';
