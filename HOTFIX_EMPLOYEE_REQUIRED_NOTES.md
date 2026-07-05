# Hotfix: employee_required Import

Fixed `NameError: name 'employee_required' is not defined`.

The OPS client detail page uses `@employee_required`, so `clients/views.py` now imports it from `core.permissions`.

After replacing the project, run:

```bash
pip install -r requirements.txt --upgrade
python manage.py makemigrations
python manage.py migrate
python manage.py runserver
```
