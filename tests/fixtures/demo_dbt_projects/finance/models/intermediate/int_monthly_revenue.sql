with invoices as (
    select * from {{ ref('stg_invoices') }}
)

select
    date_trunc('month', invoice_date)::date as month,
    count(*) as invoice_count,
    sum(amount) as gross_revenue,
    sum(case when status = 'paid' then amount else 0 end) as collected_revenue,
    sum(case when status = 'pending' then amount else 0 end) as pending_revenue,
    sum(case when status = 'overdue' then amount else 0 end) as overdue_revenue,
    count(case when status = 'paid' then 1 end) as paid_invoices,
    count(case when status = 'overdue' then 1 end) as overdue_invoices
from invoices
group by date_trunc('month', invoice_date)::date
