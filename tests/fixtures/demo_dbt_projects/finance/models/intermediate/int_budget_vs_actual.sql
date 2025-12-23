with budgets as (
    select * from {{ ref('stg_budgets') }}
),

expenses as (
    select
        date_trunc('month', expense_date)::date as month,
        category,
        sum(amount) as actual_amount
    from {{ ref('stg_expenses') }}
    group by date_trunc('month', expense_date)::date, category
)

select
    b.fiscal_year,
    b.fiscal_quarter,
    b.fiscal_period,
    b.department,
    b.category,
    b.budgeted_amount,
    coalesce(e.actual_amount, 0) as actual_amount,
    b.budgeted_amount - coalesce(e.actual_amount, 0) as variance,
    case
        when b.budgeted_amount > 0 then coalesce(e.actual_amount, 0) / b.budgeted_amount
        else 0
    end as utilization_rate
from budgets b
left join expenses e on b.category = e.category
