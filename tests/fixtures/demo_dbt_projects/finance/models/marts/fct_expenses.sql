with expenses as (
    select * from {{ ref('stg_expenses') }}
)

select
    expense_id,
    expense_date,
    category,
    subcategory,
    amount,
    vendor,
    approved_by,
    expense_type,
    case
        when amount >= 10000 then 'large'
        when amount >= 1000 then 'medium'
        else 'small'
    end as expense_size,
    current_timestamp as _updated_at
from expenses
