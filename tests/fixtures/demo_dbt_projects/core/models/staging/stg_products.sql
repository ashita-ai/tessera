with source as (
    select * from {{ ref('raw_products') }}
)

select
    product_id,
    product_name,
    category,
    subcategory,
    cost,
    list_price,
    list_price - cost as margin,
    case when is_active = 'true' then true else false end as is_active,
    current_timestamp as _loaded_at
from source
