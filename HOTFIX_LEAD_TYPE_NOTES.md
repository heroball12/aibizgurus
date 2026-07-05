# Hotfix: CRM Lead Type Field

Fixed Django system check errors:

- `crm.LeadAdmin.list_display[2]` referenced `lead_scope`
- `crm.LeadAdmin.list_filter[0]` referenced `lead_scope`

The existing Lead model already uses `lead_type` to separate:
- `internal_sales` = AI Business Gurus internal CRM leads
- `client_customer` = leads captured for a client

This hotfix updates admin/views/templates to consistently use `lead_type`.

Run:

```bash
pip install -r requirements.txt --upgrade
python manage.py makemigrations
python manage.py migrate
python manage.py seed_industries
python manage.py runserver
```
