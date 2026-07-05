# Hotfix: owner_required Import

Fixed:

`NameError: name 'user_passes_test' is not defined`

Cause:
`core/permissions.py` used `user_passes_test` for `owner_required`, but the import was missing.

This hotfix adds:

```python
from django.contrib.auth.decorators import user_passes_test
```

Run:

```bash
pip install -r requirements.txt --upgrade
python manage.py makemigrations
python manage.py migrate
python manage.py seed_industries
python manage.py runserver
```
