with source as (
    select * from {{ ref('raw_website_sessions') }}
)

select
    session_id,
    visitor_id,
    cast(session_date as date) as session_date,
    source,
    medium,
    case when campaign_id = 'null' then null else campaign_id end as campaign_id,
    pages_viewed,
    session_duration_sec,
    session_duration_sec / 60.0 as session_duration_min,
    case when converted = '1' then true else false end as converted,
    current_timestamp as _loaded_at
from source
