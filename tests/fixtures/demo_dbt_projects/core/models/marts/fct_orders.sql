with orders as (
    select * from {{ ref('int_orders_enriched') }}
),

customers as (
    select customer_id, segment, country from {{ ref('stg_customers') }}
)

select
    o.order_id,
    o.customer_id,
    c.segment as customer_segment,
    c.country as customer_country,
    o.order_date,
    o.status,
    o.shipping_method,
    o.discount_code,
    o.has_discount,
    o.gross_amount,
    o.total_cost,
    o.gross_margin,
    o.item_count,
    o.paid_amount,
    o.last_payment_date,
    case
        when o.status = 'refunded' then 0
        else o.gross_amount
    end as net_revenue,
    case
        when o.gross_amount >= 200 then 'large'
        when o.gross_amount >= 100 then 'medium'
        else 'small'
    end as order_size,
    current_timestamp as _updated_at
from orders o
left join customers c on o.customer_id = c.customer_id
