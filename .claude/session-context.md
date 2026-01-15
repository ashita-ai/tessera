# Session Context: UI Filter Width Fix

## Current Task
Fix the filter row width on Proposals and Assets pages to match the table width below (like Audit Log does correctly).

## Problem
The filter row (containing dropdowns) should span the full width and match the data table below it. The Audit Log page does this correctly. Proposals and Assets pages do not.

## What Was Tried
1. Changed from `display: flex` to `display: grid` with `grid-template-columns: 1fr 1fr 1fr auto` (proposals) and `1fr 1fr 1fr 1fr auto` (assets)
2. Rebuilt Docker containers multiple times
3. User reports still seeing no changes despite code being updated in container

## Uncommitted Files (from git status)
- `src/tessera/static/js/api.js` (modified)
- `src/tessera/templates/audit_log.html` (modified)
- `src/tessera/templates/proposals.html` (modified)

Note: assets.html already has the grid layout (may have been committed already)

## Reference Implementation (works correctly)
`/src/tessera/templates/audit_log.html` line 9:
```html
<div class="filters" style="margin-bottom: 1rem; display: grid; grid-template-columns: 1fr 1fr auto; gap: 0.75rem; align-items: end; padding: 0.75rem 1rem; background: var(--light-gray); border: 1px solid #ddd;">
```

## Current State of proposals.html (line 9)
```html
<div class="filters" style="margin-bottom: 1rem; display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 0.75rem; align-items: end; padding: 0.75rem 1rem; background: var(--light-gray); border: 1px solid #ddd;">
```

## Current State of assets.html (line 12)
```html
<div class="filters" style="margin-bottom: 1rem; display: grid; grid-template-columns: 1fr 1fr 1fr 1fr auto; gap: 0.75rem; align-items: end; padding: 0.75rem 1rem; background: var(--light-gray); border: 1px solid #ddd;">
```

## User's Exact Request
"i want the selector menu width to be equal to the content width below it" and "the audit page does it correctly"

## Docker Environment
- Dev server: port 8001 (`docker-compose.dev.yml` with project name `tessera-dev`)
- Production server: port 8000 (`docker-compose.yml`)

## Problem Analysis
The grid layout IS in the code. The issue is that even with CSS grid, the visual result doesn't match what the user expects. The Audit Log has 2 filter dropdowns and 4 table columns. Proposals has 3 filter dropdowns and 7 table columns. The ratio mismatch may be why it looks different.

## Next Steps to Try
1. User should hard refresh (Cmd+Shift+R) and verify looking at port 8001
2. If grid isn't visually working, consider: making filter dropdowns wider (larger fr values), or constraining table width
3. The core issue may be a design/UX question about whether filters should visually align with table columns
