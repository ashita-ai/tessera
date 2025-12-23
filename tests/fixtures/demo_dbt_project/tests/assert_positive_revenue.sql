-- Singular test: ensure all completed orders have positive revenue
-- This returns rows that FAIL the test

select
    order_id,
    revenue
from {{ ref('fct_orders') }}
where status = 'completed' and revenue <= 0
