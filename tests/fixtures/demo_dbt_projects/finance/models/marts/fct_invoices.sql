with invoices as (
    select * from {{ ref('stg_invoices') }}
)

select
    invoice_id,
    customer_id,
    invoice_date,
    due_date,
    amount,
    status,
    currency,
    payment_terms_days,
    is_overdue,
    case
        when amount >= 500 then 'large'
        when amount >= 100 then 'medium'
        else 'small'
    end as invoice_size,
    current_timestamp as _updated_at
from invoices
