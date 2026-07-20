# 已确认业务与数据规则

## 源数据粒度与业务键

`orders` 每行代表一张订单，以 `order_id` 为主键；`order_details` 每行代表订单中的一个商品，以 `(order_id, product_id)` 为组合主键。客户、员工、商品分别使用 `customer_id`、`employee_id`、`product_id` 关联，所有可依赖关系以源 DDL 的主键和外键为准。

## CDC 与去重

AWS DMS 的操作类型、提交时间和文件审计字段不属于 Northwind 源 Schema，只有在实际 DMS 配置确认后才能用于 CDC 排序与去重。提案应按源业务键保留最新版本并处理删除事件，但不得虚构具体 DMS 列名，也不得声称 CDC 已验证。

## 事件时间与迟到数据

每日销售按 `orders.order_date` 归属日期。`required_date` 和 `shipped_date` 用于配送分析；源 Schema 没有统一事件时间或摄取时间字段。时区、迟到边界、水位线和历史回补窗口均待确认。

## 指标口径

订单行毛额为 `unit_price * quantity`；订单行折扣金额为 `unit_price * quantity * discount`；订单行净销售额为 `unit_price * quantity * (1 - discount)`。订单净销售额是同一 `order_id` 下全部明细净销售额之和。`freight` 单独作为运费指标，不计入净销售额。`shipped_date > required_date` 表示延期发货。金额只标记为源系统金额，不做汇率换算。

## 空值与数据质量

源主键和组合主键字段不得为空。需要检查订单明细引用的订单和商品、订单引用的客户和员工、`quantity` 与 `unit_price` 的合理性，以及 `discount` 是否位于 0 到 1 之间。发现异常时应记录或隔离，不得伪造维度值，也不得声称检查已经执行。

## PII 与权限

`customers`、`employees` 和 `suppliers` 中的姓名、联系人、电话与地址类字段按潜在敏感字段处理。发布层只暴露获批字段，并使用 Unity Catalog 最小权限、审计和必要的列级控制；最终分类和脱敏方式待治理团队确认。

## 待确认规则

Northwind 没有取消、退货和币种字段，不虚构取消或退货口径，也不做币种转换。默认统计全部订单；是否只统计已发货订单仍待业务确认。DMS 删除处理、空客户订单、折扣边界异常、员工归属和配送 SLA 的最终处置规则也待确认。
