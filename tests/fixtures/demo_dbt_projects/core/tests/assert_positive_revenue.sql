-- Singular test: ensure no negative revenue
select
    order_id,
    gross_amount
from {{ ref('fct_orders') }}
where gross_amount < 0
