# Review report — Tempo 2.1.0, run 2

1 item(s) need your attention.

## ⚠ Needs confirmation

### Suppressed: "Added Linear integration to sync projects into Tempo workspaces."
Evidence: 576ca8a2d (after the window) reverts 0c7767228: "Pulled from the release. Rate limits on Linear's side make the initial sync unusable for workspaces with more than ~200 projects. Back in 2.2."
Default applied: treated as never shipped in 2.1.0. If it did reach customers, rerun with --restore-entry 0c7767228.

## Suppressed (no action expected)

### Not announced: feat(export): start work on iCal export for time entries
flag FEATURE_ICAL_EXPORT is False at the end of the window

## Informational

### Net zero inside the window: feat(ui): dark mode toggle in settings
edef93438 reverts 33f3123ba inside the window: "This reverts the dark mode work — unreadable contrast on the reports page. Will revisit after the design refresh."

### Skipped: fix(ci): correct staging deploy credentials
Internal CI configuration change with no customer-visible impact

### Skipped: chore(api): small tidy-up of the entries serializer
Internal code tidy-up with no customer-visible changes

### Skipped: feat(admin): bulk deactivate users
Feature is not implemented (raises NotImplementedError)

### Skipped: chore: update poetry.lock
Internal dependency lockfile update with no customer-visible changes

### Skipped: chore: regenerate API client from openapi spec
Internal code generation change with no customer-visible impact

## Stability summary

- 35 entr(ies) reused from the ledger, byte-identical; 0 newly generated.
- 18 commit(s) after the 2.1.0 bump: scoped to the next release.
- 10 noise and 2 dependency commit(s) excluded (listed in traceability.json).
