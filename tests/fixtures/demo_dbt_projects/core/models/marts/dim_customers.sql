with customers as (
    select * from {{ ref('stg_customers') }}
),

customer_orders as (
    select * from {{ ref('int_customer_orders') }}
)

select
    c.customer_id,
    c.email,
    c.first_name,
    c.last_name,
    c.full_name,
    c.created_at,
    c.country,
    c.segment,
    coalesce(co.total_orders, 0) as total_orders,
    coalesce(co.completed_orders, 0) as completed_orders,
    coalesce(co.refunded_orders, 0) as refunded_orders,
    coalesce(co.total_revenue, 0) as lifetime_revenue,
    coalesce(co.total_margin, 0) as lifetime_margin,
    coalesce(co.avg_order_value, 0) as avg_order_value,
    co.first_order_date,
    co.last_order_date,
    case
        when co.total_orders is null then 'never_ordered'
        when co.total_orders = 1 then 'one_time'
        when co.total_orders <= 3 then 'occasional'
        else 'frequent'
    end as order_frequency,
    case
        when co.total_revenue >= 500 then 'high_value'
        when co.total_revenue >= 200 then 'medium_value'
        else 'low_value'
    end as value_tier,
    current_timestamp as _updated_at
from customers c
left join customer_orders co on c.customer_id = co.customer_id
