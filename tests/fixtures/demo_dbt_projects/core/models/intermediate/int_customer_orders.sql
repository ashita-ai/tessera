with orders as (
    select * from {{ ref('int_orders_enriched') }}
)

select
    customer_id,
    count(*) as total_orders,
    count(case when status = 'completed' then 1 end) as completed_orders,
    count(case when status = 'refunded' then 1 end) as refunded_orders,
    sum(gross_amount) as total_revenue,
    sum(paid_amount) as total_paid,
    sum(gross_margin) as total_margin,
    min(order_date) as first_order_date,
    max(order_date) as last_order_date,
    avg(gross_amount) as avg_order_value
from orders
group by customer_id
