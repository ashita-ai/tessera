with source as (
    select * from {{ ref('raw_accounts') }}
)

select
    account_id,
    account_name,
    account_type,
    parent_account_id,
    case when is_active = 'true' then true else false end as is_active,
    case
        when parent_account_id is null then 0
        else 1
    end as account_level,
    current_timestamp as _loaded_at
from source
