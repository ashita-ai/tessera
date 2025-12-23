with source as (
    select * from {{ ref('raw_payments') }}
)

select
    payment_id,
    order_id,
    payment_method,
    amount,
    cast(payment_date as date) as payment_date,
    status,
    case
        when status = 'success' then amount
        when status = 'refunded' then -amount
        else 0
    end as net_amount,
    current_timestamp as _loaded_at
from source
