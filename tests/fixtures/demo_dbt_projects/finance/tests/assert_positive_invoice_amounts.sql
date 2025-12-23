-- Singular test: all invoices should have positive amounts
select
    invoice_id,
    amount
from {{ ref('fct_invoices') }}
where amount <= 0
