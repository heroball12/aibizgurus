# Hotfix Notes

Fixed missing Django `TEMPLATES` setting in `config/settings.py`.

Without this setting, Django raises:

`admin.E403: A 'django.template.backends.django.DjangoTemplates' instance must be configured in TEMPLATES in order to use the admin application.`

After this hotfix, continue with:

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py seed_industries
python manage.py createsuperuser
python manage.py runserver
```
