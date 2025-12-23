with channel_daily as (
    select * from {{ ref('int_channel_daily') }}
)

select
    date,
    channel,
    impressions,
    clicks,
    spend,
    conversions,
    revenue,
    ctr,
    avg_cpc,
    revenue - spend as daily_profit,
    case when spend > 0 then revenue / spend else 0 end as daily_roas,
    current_timestamp as _updated_at
from channel_daily
