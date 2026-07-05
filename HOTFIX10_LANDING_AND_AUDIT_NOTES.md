# Hotfix 10: Landing Page + Audit Admin Error

## Landing Page

The home page has been upgraded with a premium purple SaaS layout:

- Dark purple hero
- Demo/video mockup
- AI chat card
- Stats bar
- Trust/logo strip
- How It Works cards
- Industry showcase
- Strong CTA section

## Audit Error Fix

Fixed admin saves breaking with:

`no such table: audit_activitylog`

The logger now checks that the audit table exists before inserting logs.

Run:

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py check_audit
```
