with orders as (
    select * from {{ ref('stg_orders') }}
),

order_items as (
    select * from {{ ref('int_order_items_enriched') }}
),

payments as (
    select * from {{ ref('stg_payments') }}
),

order_totals as (
    select
        order_id,
        sum(line_total) as gross_amount,
        sum(line_cost) as total_cost,
        sum(line_margin) as gross_margin,
        count(*) as item_count
    from order_items
    group by order_id
),

payment_totals as (
    select
        order_id,
        sum(net_amount) as paid_amount,
        max(payment_date) as last_payment_date
    from payments
    group by order_id
)

select
    o.order_id,
    o.customer_id,
    o.order_date,
    o.status,
    o.shipping_method,
    o.discount_code,
    o.has_discount,
    coalesce(ot.gross_amount, 0) as gross_amount,
    coalesce(ot.total_cost, 0) as total_cost,
    coalesce(ot.gross_margin, 0) as gross_margin,
    coalesce(ot.item_count, 0) as item_count,
    coalesce(pt.paid_amount, 0) as paid_amount,
    pt.last_payment_date
from orders o
left join order_totals ot on o.order_id = ot.order_id
left join payment_totals pt on o.order_id = pt.order_id
