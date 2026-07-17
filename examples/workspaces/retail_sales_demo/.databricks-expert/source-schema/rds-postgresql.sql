-- Mock RDS PostgreSQL 仅结构导出，不包含任何客户记录。
CREATE TABLE public.customer (
    customer_id varchar(64) NOT NULL,
    full_name varchar(200),
    email varchar(320),
    phone varchar(40),
    postal_address text,
    loyalty_tier varchar(32),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (customer_id)
);

CREATE TABLE public.product (
    product_id varchar(64) NOT NULL,
    sku varchar(100) NOT NULL,
    product_name varchar(300) NOT NULL,
    category_id varchar(64),
    brand_name varchar(200),
    standard_cost numeric(18, 4),
    list_price numeric(18, 4),
    active_flag boolean NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (product_id),
    UNIQUE (sku)
);

CREATE TABLE public.store (
    store_id varchar(64) NOT NULL,
    store_name varchar(200) NOT NULL,
    region_code varchar(32),
    timezone_name varchar(100) NOT NULL,
    opened_date date,
    active_flag boolean NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (store_id)
);

CREATE TABLE public.inventory (
    store_id varchar(64) NOT NULL,
    product_id varchar(64) NOT NULL,
    snapshot_at timestamptz NOT NULL,
    on_hand_quantity integer NOT NULL,
    reserved_quantity integer NOT NULL,
    reorder_point integer,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (store_id, product_id, snapshot_at),
    FOREIGN KEY (store_id) REFERENCES public.store (store_id),
    FOREIGN KEY (product_id) REFERENCES public.product (product_id)
);
