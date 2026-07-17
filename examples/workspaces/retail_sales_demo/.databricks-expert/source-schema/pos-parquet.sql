-- Mock POS Parquet 销售明细记录的逻辑结构。
CREATE TABLE source.pos_sales_line (
    order_id string NOT NULL,
    order_line_id string NOT NULL,
    business_date date NOT NULL,
    event_ts timestamp NOT NULL,
    store_id string NOT NULL,
    terminal_id string,
    cashier_id string,
    customer_id string,
    product_id string NOT NULL,
    quantity decimal(18, 3) NOT NULL,
    unit_price decimal(18, 4) NOT NULL,
    discount_amount decimal(18, 4),
    tax_amount decimal(18, 4),
    currency_code string NOT NULL,
    transaction_status string NOT NULL,
    source_file_date date NOT NULL
) USING PARQUET;
