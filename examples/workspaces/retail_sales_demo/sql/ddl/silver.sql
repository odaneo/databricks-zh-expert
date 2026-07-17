-- AWS 零售销售 Mock 项目的 Silver 逻辑 DDL，仅供设计与代码生成参考。

CREATE TABLE IF NOT EXISTS silver.dim_customer (
  customer_id STRING NOT NULL COMMENT '客户业务键和受控分析标识',
  masked_email STRING COMMENT '掩码邮箱',
  masked_phone STRING COMMENT '掩码手机号',
  loyalty_tier STRING COMMENT '会员等级',
  customer_segment STRING COMMENT '非直接识别客户分群',
  effective_from TIMESTAMP NOT NULL COMMENT 'SCD2 生效时间',
  effective_to TIMESTAMP COMMENT 'SCD2 失效时间',
  is_current BOOLEAN NOT NULL COMMENT '当前版本标识',
  source_commit_ts TIMESTAMP NOT NULL COMMENT '源 CDC 提交时间',
  _processed_ts TIMESTAMP NOT NULL COMMENT 'Silver 处理时间'
)
USING DELTA
COMMENT 'Mock 脱敏客户 SCD2 维度';

CREATE TABLE IF NOT EXISTS silver.dim_product (
  product_id STRING NOT NULL COMMENT '商品业务键',
  sku STRING NOT NULL COMMENT '商品 SKU',
  product_name STRING NOT NULL COMMENT '商品名称',
  category_id STRING NOT NULL COMMENT '品类业务键',
  category_name STRING NOT NULL COMMENT '品类名称',
  brand STRING COMMENT '品牌',
  current_unit_price DECIMAL(18,2) NOT NULL COMMENT '版本内有效单价',
  active_flag BOOLEAN NOT NULL COMMENT '有效标识',
  effective_from TIMESTAMP NOT NULL COMMENT 'SCD2 生效时间',
  effective_to TIMESTAMP COMMENT 'SCD2 失效时间',
  is_current BOOLEAN NOT NULL COMMENT '当前版本标识',
  source_commit_ts TIMESTAMP NOT NULL COMMENT '源 CDC 提交时间',
  _processed_ts TIMESTAMP NOT NULL COMMENT 'Silver 处理时间'
)
USING DELTA
COMMENT 'Mock 商品 SCD2 维度';

CREATE TABLE IF NOT EXISTS silver.dim_store (
  store_id STRING NOT NULL COMMENT '门店业务键',
  store_name STRING NOT NULL COMMENT '门店名称',
  region_code STRING NOT NULL COMMENT '区域代码',
  timezone STRING NOT NULL COMMENT 'IANA 业务时区',
  opened_date DATE COMMENT '开业日期',
  active_flag BOOLEAN NOT NULL COMMENT '有效标识',
  effective_from TIMESTAMP NOT NULL COMMENT 'SCD2 生效时间',
  effective_to TIMESTAMP COMMENT 'SCD2 失效时间',
  is_current BOOLEAN NOT NULL COMMENT '当前版本标识',
  source_commit_ts TIMESTAMP NOT NULL COMMENT '源 CDC 提交时间',
  _processed_ts TIMESTAMP NOT NULL COMMENT 'Silver 处理时间'
)
USING DELTA
COMMENT 'Mock 门店 SCD2 维度';

CREATE TABLE IF NOT EXISTS silver.fact_sales (
  order_id STRING NOT NULL COMMENT '统一订单业务键',
  order_line_id STRING NOT NULL COMMENT '统一订单行业务键',
  business_date DATE NOT NULL COMMENT '销售业务日期',
  order_ts TIMESTAMP NOT NULL COMMENT 'UTC 订单时间',
  store_id STRING COMMENT '门店业务键',
  product_id STRING NOT NULL COMMENT '商品业务键',
  customer_id STRING COMMENT '受控客户分析标识',
  channel STRING NOT NULL COMMENT 'store、web、app 或 marketplace',
  quantity DECIMAL(18,3) NOT NULL COMMENT '销售或退货数量',
  gross_amount DECIMAL(18,2) NOT NULL COMMENT '折扣前金额',
  discount_amount DECIMAL(18,2) NOT NULL COMMENT '折扣金额',
  net_amount DECIMAL(18,2) NOT NULL COMMENT '净金额',
  currency_code STRING NOT NULL COMMENT '源币种代码',
  is_return BOOLEAN NOT NULL COMMENT '完成退货标识',
  is_cancelled BOOLEAN NOT NULL COMMENT '取消订单标识',
  source_type STRING NOT NULL COMMENT 'pos 或 ecommerce',
  source_event_id STRING COMMENT 'Kinesis 来源事件键',
  _processed_ts TIMESTAMP NOT NULL COMMENT 'Silver 处理时间'
)
USING DELTA
PARTITIONED BY (business_date)
COMMENT 'Mock POS 与电商统一订单行销售事实';

CREATE TABLE IF NOT EXISTS silver.fact_inventory (
  snapshot_ts TIMESTAMP NOT NULL COMMENT 'UTC 库存时点',
  business_date DATE NOT NULL COMMENT '库存业务日期',
  store_id STRING NOT NULL COMMENT '门店业务键',
  product_id STRING NOT NULL COMMENT '商品业务键',
  on_hand_quantity DECIMAL(18,3) NOT NULL COMMENT '账面库存数量',
  reserved_quantity DECIMAL(18,3) NOT NULL COMMENT '预留库存数量',
  available_quantity DECIMAL(18,3) NOT NULL COMMENT '可售库存数量',
  reorder_point DECIMAL(18,3) COMMENT '补货阈值',
  stockout_flag BOOLEAN NOT NULL COMMENT '缺货标识',
  source_commit_ts TIMESTAMP NOT NULL COMMENT '源 CDC 提交时间',
  _processed_ts TIMESTAMP NOT NULL COMMENT 'Silver 处理时间'
)
USING DELTA
PARTITIONED BY (business_date)
COMMENT 'Mock 门店商品库存时点事实';

CREATE TABLE IF NOT EXISTS silver.fact_customer_behavior (
  event_id STRING NOT NULL COMMENT '去重后的事件业务键',
  session_id STRING COMMENT '受控会话分析标识',
  event_ts TIMESTAMP NOT NULL COMMENT 'UTC 事件发生时间',
  business_date DATE NOT NULL COMMENT '行为业务日期',
  customer_id STRING COMMENT '受控客户分析标识',
  channel STRING NOT NULL COMMENT '客户渠道',
  event_type STRING NOT NULL COMMENT '浏览、加购、结算或转化事件',
  product_id STRING COMMENT '商品业务键',
  order_id STRING COMMENT '关联订单业务键',
  device_type STRING COMMENT '设备类型',
  campaign_code STRING COMMENT '活动代码',
  converted_flag BOOLEAN NOT NULL COMMENT '有效订单转化标识',
  _processed_ts TIMESTAMP NOT NULL COMMENT 'Silver 处理时间'
)
USING DELTA
PARTITIONED BY (business_date)
COMMENT 'Mock 去重客户行为事实';
