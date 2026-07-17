CREATE TABLE public.customer (
    customer_id varchar(64) NOT NULL,
    email varchar(320),
    updated_at timestamptz,
    PRIMARY KEY (customer_id)
);
