# Hotfix 8: Industry Seed Data Source

This patch makes the industry seed impossible to silently load 0 without explaining why.

## What changed

- Added `core/industry_data.json` backup source.
- Added `core/industry_loader.py`.
- `seed_industries` now prints:
  - Industry source
  - Source count
  - Created count
  - Updated count
  - Final DB count
- `verify_demo_flow` now prints loader source and source count.
- If the Python data source fails, the JSON file is used.
- If both fail, an emergency built-in list is used.

## Run

```bash
python manage.py seed_industries --clear
python manage.py verify_demo_flow --create-test
python manage.py check_signup_industries
python manage.py runserver
```

Expected:

```text
Industry source: python
Templates in source: 101
After: 101
PASS: database-backed industry signup/demo flow is connected.
```
