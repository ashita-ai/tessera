with source as (
    select * from {{ ref('raw_ad_spend') }}
)

select
    spend_id,
    campaign_id,
    cast(spend_date as date) as spend_date,
    impressions,
    clicks,
    spend,
    case when impressions > 0 then clicks::float / impressions else 0 end as ctr,
    case when clicks > 0 then spend / clicks else 0 end as cpc,
    case when impressions > 0 then (spend / impressions) * 1000 else 0 end as cpm,
    current_timestamp as _loaded_at
from source
