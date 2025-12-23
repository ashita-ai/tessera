with source as (
    select * from {{ ref('raw_orders') }}
)

select
    order_id,
    customer_id,
    cast(order_date as date) as order_date,
    status,
    shipping_method,
    coalesce(discount_code, 'NONE') as discount_code,
    case when discount_code is not null then true else false end as has_discount,
    current_timestamp as _loaded_at
from source
