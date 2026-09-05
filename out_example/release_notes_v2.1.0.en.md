# Tempo 2.1.0

> ⚠ **Before you upgrade — action required**
>
> - The `db_url` environment variable has been renamed to `TEMPO_DATABASE__URL`—update your deployment configuration before upgrading or the application will fail to start.
> - Removed deprecated `/v0` API endpoints; update any integrations or scripts to use `/v1` or later endpoints instead.
> - Dropped support for Python 3.9; you must now run Tempo on Python 3.10 or later.

## What's changed

- Added weekly summary report that shows time logged per project and can be exported as CSV.
- Added `/v1/entries/bulk` endpoint to create up to 200 time entries in a single request.
- Hourly rates can now be set per project and will override the user's default rate when calculating billing.
- Added hours overview report grouped by client
- Added optional weekly email digest that summarizes logged hours for users who opt in.

## What's improved

- Added keyboard shortcuts for timer control: `Alt+S` to start or stop the timer and `Alt+X` to switch projects.
- Weekly reports now load significantly faster due to database indexing improvements.
- Project list requests are now cached for 60 seconds per workspace, reducing load times when viewing projects multiple times.
- Timer now detects when you've been idle for 10 minutes and prompts you to discard unattended time.

## What's fixed

- Fixed timer drift that caused inaccurate time tracking after approximately 6 hours of continuous running.
- Weekly report totals now correctly include time entries from the last day of the selected date range.
- Fixed VAT calculation rounding error for invoices with amounts above 1000 euros where tax was incorrectly rounded per line item instead of on the total
- Creating a time entry without a `project_id` now returns a 422 error with a clear message instead of a 500 error.
- Fixed an issue where timers continued running in the background after logging out.
- Session cookies now include `SameSite` and `Secure` attributes to improve security against cross-site attacks.
- CSV import no longer silently drops rows with empty descriptions; they are now imported with `(no description)` as placeholder text.
- Fixed rounding differences between invoice preview and final PDF that could cause totals to differ by small amounts.
- CSV downloads now use the workspace timezone instead of the browser timezone for date formatting.
- Fixed an issue where workspaces spanning multiple regions would receive duplicate weekly digest notifications.
