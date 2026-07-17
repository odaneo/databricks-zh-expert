-- Mock Kinesis JSON 事件载荷的逻辑结构。
CREATE TABLE source.order_event (
    event_id string NOT NULL,
    event_type string NOT NULL,
    event_ts timestamp NOT NULL,
    order_id string NOT NULL,
    customer_id string,
    channel_code string NOT NULL,
    order_status string NOT NULL,
    currency_code string NOT NULL,
    order_amount decimal(18, 4),
    items_json string,
    schema_version integer NOT NULL
) USING JSON;

CREATE TABLE source.payment_event (
    event_id string NOT NULL,
    event_type string NOT NULL,
    event_ts timestamp NOT NULL,
    payment_id string NOT NULL,
    order_id string NOT NULL,
    payment_status string NOT NULL,
    payment_method string,
    payment_amount decimal(18, 4),
    currency_code string NOT NULL,
    schema_version integer NOT NULL
) USING JSON;

CREATE TABLE source.behavior_event (
    event_id string NOT NULL,
    event_type string NOT NULL,
    event_ts timestamp NOT NULL,
    session_id string NOT NULL,
    customer_id string,
    anonymous_id string,
    page_name string,
    product_id string,
    referrer_channel string,
    attributes_json string,
    schema_version integer NOT NULL
) USING JSON;
