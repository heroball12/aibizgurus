# Hotfix: Industry Seeding

Industries now seed more reliably.

## What changed

- Added reusable `core/industry_data.py`.
- Added `core/seed.py`.
- Improved `python manage.py seed_industries`.
- Added `python manage.py check_industries`.
- Added automatic seeding after migrations through `post_migrate`.

## Run

```bash
python manage.py migrate
python manage.py seed_industries --clear
python manage.py check_industries
```

You should see the industry count and sample industries.
