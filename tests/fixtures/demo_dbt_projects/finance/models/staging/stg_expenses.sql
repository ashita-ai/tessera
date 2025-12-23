with source as (
    select * from {{ ref('raw_expenses') }}
)

select
    expense_id,
    cast(expense_date as date) as expense_date,
    category,
    subcategory,
    amount,
    vendor,
    approved_by,
    case
        when category = 'hr' and subcategory = 'payroll' then 'recurring'
        else 'one_time'
    end as expense_type,
    current_timestamp as _loaded_at
from source
