with source as (
    select * from {{ ref('raw_conversions') }}
)

select
    conversion_id,
    campaign_id,
    customer_id,
    cast(conversion_date as date) as conversion_date,
    conversion_type,
    revenue,
    case when revenue > 0 then true else false end as is_revenue_generating,
    current_timestamp as _loaded_at
from source
