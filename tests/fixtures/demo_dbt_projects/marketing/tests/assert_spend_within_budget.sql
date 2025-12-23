-- Singular test: campaign spend should not exceed budget
select
    campaign_id,
    campaign_name,
    budget,
    total_spend,
    total_spend - budget as overspend
from {{ ref('dim_campaigns') }}
where total_spend > budget * 1.1  -- 10% tolerance
