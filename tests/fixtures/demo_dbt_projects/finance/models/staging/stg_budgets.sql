with source as (
    select * from {{ ref('raw_budgets') }}
)

select
    budget_id,
    fiscal_year,
    fiscal_quarter,
    department,
    category,
    budgeted_amount,
    fiscal_year || '-' || fiscal_quarter as fiscal_period,
    current_timestamp as _loaded_at
from source
