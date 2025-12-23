with revenue as (
    select * from {{ ref('int_monthly_revenue') }}
),

expenses as (
    select
        month,
        sum(total_expenses) as total_expenses
    from {{ ref('int_expense_by_category') }}
    group by month
)

select
    r.month,
    r.gross_revenue,
    r.collected_revenue,
    r.pending_revenue,
    r.overdue_revenue,
    r.invoice_count,
    coalesce(e.total_expenses, 0) as total_expenses,
    r.collected_revenue - coalesce(e.total_expenses, 0) as net_income,
    case
        when r.collected_revenue > 0 then (r.collected_revenue - coalesce(e.total_expenses, 0)) / r.collected_revenue
        else 0
    end as profit_margin,
    current_timestamp as _updated_at
from revenue r
left join expenses e on r.month = e.month
