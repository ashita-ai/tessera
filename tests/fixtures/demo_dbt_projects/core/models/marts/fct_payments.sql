with payments as (
    select * from {{ ref('stg_payments') }}
),

orders as (
    select order_id, customer_id, order_date from {{ ref('stg_orders') }}
)

select
    p.payment_id,
    p.order_id,
    o.customer_id,
    p.payment_method,
    p.amount,
    p.net_amount,
    p.payment_date,
    o.order_date,
    p.status,
    case
        when p.status = 'success' then true
        else false
    end as is_successful,
    p.payment_date::date - o.order_date::date as days_to_payment,
    current_timestamp as _updated_at
from payments p
left join orders o on p.order_id = o.order_id
