-- AWS 零售销售 Mock 项目的 Gold 逻辑 DDL，仅供设计与代码生成参考。
-- Gold 不包含原始姓名、邮箱、手机号或地址。

CREATE TABLE IF NOT EXISTS gold.daily_sales (
  business_date DATE NOT NULL COMMENT '销售业务日期',
  store_id STRING NOT NULL COMMENT '门店业务键',
  channel STRING NOT NULL COMMENT '销售渠道',
  product_id STRING NOT NULL COMMENT '商品业务键',
  gross_sales_amount DECIMAL(18,2) NOT NULL COMMENT '折扣前销售额',
  discount_amount DECIMAL(18,2) NOT NULL COMMENT '折扣金额',
  net_sales_amount DECIMAL(18,2) NOT NULL COMMENT '净销售额',
  refund_amount DECIMAL(18,2) NOT NULL COMMENT '退款金额',
  order_count BIGINT NOT NULL COMMENT '去重订单数',
  sales_quantity DECIMAL(18,3) NOT NULL COMMENT '净销售数量',
  average_order_value DECIMAL(18,2) COMMENT '平均订单净额',
  refreshed_at TIMESTAMP NOT NULL COMMENT '产品刷新时间',
  quality_status STRING NOT NULL COMMENT '发布质量状态'
)
USING DELTA
PARTITIONED BY (business_date)
COMMENT 'Mock 每日销售数据产品';

CREATE TABLE IF NOT EXISTS gold.product_performance (
  business_date DATE NOT NULL COMMENT '销售业务日期',
  product_id STRING NOT NULL COMMENT '商品业务键',
  channel STRING NOT NULL COMMENT '销售渠道',
  category_id STRING NOT NULL COMMENT '品类业务键',
  gross_sales_amount DECIMAL(18,2) NOT NULL COMMENT '折扣前销售额',
  net_sales_amount DECIMAL(18,2) NOT NULL COMMENT '净销售额',
  sales_quantity DECIMAL(18,3) NOT NULL COMMENT '非退货销售数量',
  return_quantity DECIMAL(18,3) NOT NULL COMMENT '退货数量',
  return_rate DECIMAL(18,6) COMMENT '退货率',
  discount_rate DECIMAL(18,6) COMMENT '折扣率',
  category_rank BIGINT COMMENT '品类内表现排名',
  refreshed_at TIMESTAMP NOT NULL COMMENT '产品刷新时间',
  quality_status STRING NOT NULL COMMENT '发布质量状态'
)
USING DELTA
PARTITIONED BY (business_date)
COMMENT 'Mock 商品表现数据产品';

CREATE TABLE IF NOT EXISTS gold.inventory_health (
  snapshot_date DATE NOT NULL COMMENT '库存快照日期',
  store_id STRING NOT NULL COMMENT '门店业务键',
  product_id STRING NOT NULL COMMENT '商品业务键',
  available_quantity DECIMAL(18,3) NOT NULL COMMENT '日末可售库存',
  reorder_point DECIMAL(18,3) COMMENT '补货阈值',
  stockout_flag BOOLEAN NOT NULL COMMENT '缺货标识',
  days_of_supply DECIMAL(18,3) COMMENT '预计库存覆盖天数',
  inventory_turnover DECIMAL(18,6) COMMENT '库存周转指标',
  refreshed_at TIMESTAMP NOT NULL COMMENT '产品刷新时间',
  quality_status STRING NOT NULL COMMENT '发布质量状态'
)
USING DELTA
PARTITIONED BY (snapshot_date)
COMMENT 'Mock 库存健康数据产品';

CREATE TABLE IF NOT EXISTS gold.customer_channel (
  business_date DATE NOT NULL COMMENT '业务日期',
  customer_segment STRING NOT NULL COMMENT '非直接识别客户分群',
  channel STRING NOT NULL COMMENT '客户渠道',
  new_customer_count BIGINT NOT NULL COMMENT '新客户数',
  returning_customer_count BIGINT NOT NULL COMMENT '回访客户数',
  purchasing_customer_count BIGINT NOT NULL COMMENT '购买客户数',
  conversion_rate DECIMAL(18,6) COMMENT '会话到订单转化率',
  repeat_purchase_rate DECIMAL(18,6) COMMENT '复购率',
  net_sales_amount DECIMAL(18,2) NOT NULL COMMENT '渠道净销售额',
  channel_order_count BIGINT NOT NULL COMMENT '渠道订单数',
  refreshed_at TIMESTAMP NOT NULL COMMENT '产品刷新时间',
  quality_status STRING NOT NULL COMMENT '发布质量状态'
)
USING DELTA
PARTITIONED BY (business_date)
COMMENT 'Mock 客户分群与渠道数据产品';
