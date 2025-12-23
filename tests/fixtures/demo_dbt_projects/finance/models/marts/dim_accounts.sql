with accounts as (
    select * from {{ ref('stg_accounts') }}
),

parent_accounts as (
    select account_id, account_name as parent_account_name
    from accounts
    where parent_account_id is null
)

select
    a.account_id,
    a.account_name,
    a.account_type,
    a.parent_account_id,
    p.parent_account_name,
    a.is_active,
    a.account_level,
    current_timestamp as _updated_at
from accounts a
left join parent_accounts p on a.parent_account_id = p.account_id
