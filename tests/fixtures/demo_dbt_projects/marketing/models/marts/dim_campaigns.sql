with campaign_perf as (
    select * from {{ ref('int_campaign_performance') }}
)

select
    campaign_id,
    campaign_name,
    channel,
    start_date,
    end_date,
    duration_days,
    budget,
    status,
    total_impressions,
    total_clicks,
    total_spend,
    total_conversions,
    revenue_conversions,
    total_revenue,
    ctr,
    conversion_rate,
    cost_per_conversion,
    net_profit,
    roas,
    case
        when roas >= 3 then 'high_performer'
        when roas >= 1 then 'break_even'
        else 'underperformer'
    end as performance_tier,
    case
        when total_spend / nullif(budget, 0) >= 0.9 then 'fully_utilized'
        when total_spend / nullif(budget, 0) >= 0.5 then 'partially_utilized'
        else 'underutilized'
    end as budget_utilization,
    current_timestamp as _updated_at
from campaign_perf
