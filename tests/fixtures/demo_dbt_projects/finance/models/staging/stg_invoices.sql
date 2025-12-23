with source as (
    select * from {{ ref('raw_invoices') }}
)

select
    invoice_id,
    customer_id,
    cast(invoice_date as date) as invoice_date,
    cast(due_date as date) as due_date,
    amount,
    status,
    currency,
    due_date::date - invoice_date::date as payment_terms_days,
    case
        when status = 'overdue' then true
        else false
    end as is_overdue,
    current_timestamp as _loaded_at
from source
