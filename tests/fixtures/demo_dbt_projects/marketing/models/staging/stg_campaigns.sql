with source as (
    select * from {{ ref('raw_campaigns') }}
)

select
    campaign_id,
    campaign_name,
    channel,
    cast(start_date as date) as start_date,
    cast(end_date as date) as end_date,
    budget,
    status,
    end_date::date - start_date::date as duration_days,
    current_timestamp as _loaded_at
from source
