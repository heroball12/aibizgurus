# Hotfix: Signup Industry Dropdown

The database was seeded correctly, but the signup page was only showing Generic Local Service.

This hotfix changes signup to:

- Seed industries automatically if the table is empty.
- Load all industry templates instead of filtering by `is_supported`.
- Show a visible count of loaded templates on the signup page.
- Display dropdown options as `Category — Industry`.

## Verify

Run:

```bash
python manage.py check_industries
python manage.py runserver
```

Then open:

```text
http://127.0.0.1:8000/accounts/signup/
```

You should see the count and all industries in the dropdown.
