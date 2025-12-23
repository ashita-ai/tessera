with orders as (
    select * from {{ ref('fct_orders') }}
)

select
    order_date,
    count(*) as order_count,
    count(distinct customer_id) as unique_customers,
    sum(gross_amount) as gross_revenue,
    sum(net_revenue) as net_revenue,
    sum(total_cost) as total_cost,
    sum(gross_margin) as gross_margin,
    sum(item_count) as items_sold,
    avg(gross_amount) as avg_order_value,
    count(case when has_discount then 1 end) as discounted_orders,
    sum(case when customer_segment = 'enterprise' then net_revenue else 0 end) as enterprise_revenue,
    sum(case when customer_segment = 'smb' then net_revenue else 0 end) as smb_revenue,
    sum(case when customer_segment = 'startup' then net_revenue else 0 end) as startup_revenue
from orders
where status != 'refunded'
group by order_date
