-- Singular test: products should have positive margin
select
    product_id,
    product_name,
    cost,
    list_price,
    margin
from {{ ref('dim_products') }}
where margin < 0
  and is_active = true
