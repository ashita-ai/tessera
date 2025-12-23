with campaigns as (
    select * from {{ ref('stg_campaigns') }}
),

spend as (
    select
        campaign_id,
        sum(impressions) as total_impressions,
        sum(clicks) as total_clicks,
        sum(spend) as total_spend
    from {{ ref('stg_ad_spend') }}
    group by campaign_id
),

conversions as (
    select
        campaign_id,
        count(*) as total_conversions,
        count(case when is_revenue_generating then 1 end) as revenue_conversions,
        sum(revenue) as total_revenue
    from {{ ref('stg_conversions') }}
    group by campaign_id
)

select
    c.campaign_id,
    c.campaign_name,
    c.channel,
    c.start_date,
    c.end_date,
    c.duration_days,
    c.budget,
    c.status,
    coalesce(s.total_impressions, 0) as total_impressions,
    coalesce(s.total_clicks, 0) as total_clicks,
    coalesce(s.total_spend, 0) as total_spend,
    coalesce(cv.total_conversions, 0) as total_conversions,
    coalesce(cv.revenue_conversions, 0) as revenue_conversions,
    coalesce(cv.total_revenue, 0) as total_revenue,
    case when s.total_impressions > 0 then s.total_clicks::float / s.total_impressions else 0 end as ctr,
    case when s.total_clicks > 0 then cv.total_conversions::float / s.total_clicks else 0 end as conversion_rate,
    case when cv.total_conversions > 0 then s.total_spend / cv.total_conversions else null end as cost_per_conversion,
    coalesce(cv.total_revenue, 0) - coalesce(s.total_spend, 0) as net_profit,
    case when s.total_spend > 0 then cv.total_revenue / s.total_spend else 0 end as roas
from campaigns c
left join spend s on c.campaign_id = s.campaign_id
left join conversions cv on c.campaign_id = cv.campaign_id
