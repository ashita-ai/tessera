with budget_actual as (
    select * from {{ ref('int_budget_vs_actual') }}
)

select
    fiscal_year,
    fiscal_quarter,
    fiscal_period,
    department,
    category,
    budgeted_amount,
    actual_amount,
    variance,
    utilization_rate,
    case
        when utilization_rate > 1.1 then 'over_budget'
        when utilization_rate >= 0.9 then 'on_track'
        when utilization_rate >= 0.5 then 'under_utilized'
        else 'significantly_under'
    end as budget_status,
    current_timestamp as _updated_at
from budget_actual
