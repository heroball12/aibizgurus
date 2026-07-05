# Login + Client UI Cleanup Patch

## Smart Login Redirect

Employees/admins now log in through the same login page as clients, but are routed automatically:

- Client users -> `/portal/`
- Employee/Admin/Superuser users -> `/ops/`

This is handled by `RoleAwareLoginView` in `accounts/views.py`.

## Cleaner Client Side

Updated client portal templates to reduce clutter:

- Simplified dashboard header
- Cleaner assistant row instead of heavy cards
- Simplified quick actions sidebar
- Cleaner lead inbox
- Cleaner business info page
- Cleaner assistant settings page
- Cleaner integrations page
- Clearer shared login page copy

## Still Same Full Project

This patch keeps all prior features:
- OpenAI
- Twilio voice/SMS
- CRM
- Billing placeholders
- Industry templates
- Encrypted integrations
- Staff dark command center
