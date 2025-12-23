with spend as (
    select * from {{ ref('stg_ad_spend') }}
),

campaigns as (
    select campaign_id, channel from {{ ref('stg_campaigns') }}
),

conversions as (
    select
        campaign_id,
        conversion_date,
        count(*) as conversions,
        sum(revenue) as revenue
    from {{ ref('stg_conversions') }}
    group by campaign_id, conversion_date
)

select
    s.spend_date as date,
    c.channel,
    sum(s.impressions) as impressions,
    sum(s.clicks) as clicks,
    sum(s.spend) as spend,
    coalesce(sum(cv.conversions), 0) as conversions,
    coalesce(sum(cv.revenue), 0) as revenue,
    case when sum(s.impressions) > 0 then sum(s.clicks)::float / sum(s.impressions) else 0 end as ctr,
    case when sum(s.clicks) > 0 then sum(s.spend) / sum(s.clicks) else 0 end as avg_cpc
from spend s
join campaigns c on s.campaign_id = c.campaign_id
left join conversions cv on s.campaign_id = cv.campaign_id and s.spend_date = cv.conversion_date
group by s.spend_date, c.channel
