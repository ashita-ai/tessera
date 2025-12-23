with products as (
    select * from {{ ref('stg_products') }}
),

product_sales as (
    select
        product_id,
        sum(quantity) as total_units_sold,
        sum(line_total) as total_revenue,
        sum(line_margin) as total_margin,
        count(distinct order_id) as order_count
    from {{ ref('int_order_items_enriched') }}
    group by product_id
)

select
    p.product_id,
    p.product_name,
    p.category,
    p.subcategory,
    p.cost,
    p.list_price,
    p.margin,
    p.is_active,
    coalesce(ps.total_units_sold, 0) as total_units_sold,
    coalesce(ps.total_revenue, 0) as total_revenue,
    coalesce(ps.total_margin, 0) as total_margin,
    coalesce(ps.order_count, 0) as order_count,
    case
        when ps.total_revenue >= 500 then 'top_seller'
        when ps.total_revenue >= 200 then 'good_seller'
        when ps.total_revenue > 0 then 'slow_mover'
        else 'no_sales'
    end as sales_tier,
    current_timestamp as _updated_at
from products p
left join product_sales ps on p.product_id = ps.product_id
