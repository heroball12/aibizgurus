# Hotfix 9: Industries Page Uses Same Source as Signup

The signup dropdown was showing industries, but `/industries/` was still using the old database-only `is_supported=True` query.

This patch changes `/industries/` and the home preview to use the same industry option loader as signup:

- Database first
- Seed if empty
- Built-in fallback if needed

The industries page now shows:
- Template count
- Source: database/python/json/emergency depending on path

Verify:

```bash
python manage.py seed_industries --clear
python manage.py check_signup_industries
python manage.py runserver
```

Then open:

```text
http://127.0.0.1:8000/industries/
```
