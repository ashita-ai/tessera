with expenses as (
    select * from {{ ref('stg_expenses') }}
)

select
    date_trunc('month', expense_date)::date as month,
    category,
    subcategory,
    sum(amount) as total_expenses,
    count(*) as expense_count,
    avg(amount) as avg_expense
from expenses
group by date_trunc('month', expense_date)::date, category, subcategory
