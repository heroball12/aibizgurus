# Hotfix 6: Signup Industry Fallback

The database can show seeded industries in management commands while the web signup page still sees an empty table if the web process is pointed at another sqlite file/environment.

This hotfix makes signup independent of that failure mode:

- Signup first tries the database.
- If the database returns 0 industries, it falls back to the built-in `core/industry_data.py` list.
- The page shows `Source: database` or `Source: builtin`.
- On signup, if the selected industry came from the built-in list, the app creates that industry template in the database before creating the AI assistant.

## Verify

```bash
python manage.py check_signup_industries
python manage.py runserver
```

Then open:

```text
http://127.0.0.1:8000/accounts/signup/
```

You should see `101 industry templates loaded` and `Source: database` or `Source: builtin`.
