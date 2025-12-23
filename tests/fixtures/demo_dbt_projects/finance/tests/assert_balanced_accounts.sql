-- Singular test: revenue and expense accounts should have parent
select
    account_id,
    account_name,
    account_type
from {{ ref('dim_accounts') }}
where account_type in ('revenue', 'expense')
  and parent_account_id is null
  and account_level > 0
