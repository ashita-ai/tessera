-- Singular test: ensure orders have at least one item
select
    o.order_id
from {{ ref('fct_orders') }} o
left join {{ ref('int_order_items_enriched') }} oi on o.order_id = oi.order_id
where oi.order_item_id is null
