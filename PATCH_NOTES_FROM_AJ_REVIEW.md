# AJ Review Patch

## Fixed

- Logout now works with the normal nav link.
- Django admin compatibility issue addressed by upgrading dependency from Django 5.0.7 to Django 5.2.x.
- Integrations page simplified.
- OpenAI uses AI Business Gurus platform key by default.
- Clients can add their own OpenAI key later if desired.
- Added in-app Demo Setup Guide.
- OPS dashboard client rows are clickable.
- OPS can open a client workspace and view that client’s assistants, captured leads, and conversations.
- Internal CRM is now for AI Business Gurus prospects/sales leads only.
- Client-captured leads are separated under the related client.
- Client dashboard copy and OPS copy cleaned up.

## Important after pulling this version

Because requirements changed, run:

```bash
pip install -r requirements.txt --upgrade
python manage.py makemigrations
python manage.py migrate
python manage.py runserver
```

If you already had an old virtual environment with Django 5.0.7, the `--upgrade` matters.
