import hashlib
import json
from urllib.parse import urlsplit

from django.db import migrations


def group_companies(apps, schema_editor):
    Company = apps.get_model("crm", "Company")
    Lead = apps.get_model("crm", "Lead")
    alias = schema_editor.connection.alias
    known = dict(Company.objects.using(alias).exclude(match_key=None).values_list("match_key", "pk"))
    pending = []
    for lead in Lead.objects.using(alias).filter(lead_type="internal_sales", company__isnull=True).exclude(business_name="").iterator(chunk_size=500):
        url = (lead.website or "").strip().lower()
        try:
            domain = (urlsplit(url if "://" in url else "https://" + url).hostname or "").removeprefix("www.")
        except ValueError:
            domain = ""
        parts = [" ".join(str(s or "").casefold().split()) for s in (lead.business_name, domain, lead.city, lead.state)]
        match_key = hashlib.sha256(json.dumps(parts).encode()).hexdigest()
        if match_key not in known:
            company, _ = Company.objects.using(alias).get_or_create(match_key=match_key, defaults={
                "name": lead.business_name,
                **{field: getattr(lead, field) for field in ("industry", "website", "address", "city", "state", "zip_code")},
                "phone": lead.phone if not (lead.name or lead.point_of_contact) else "",
            })
            known[match_key] = company.pk
        lead.company_id = known[match_key]
        pending.append(lead)
        if len(pending) == 500:
            Lead.objects.using(alias).bulk_update(pending, ["company"], batch_size=500)
            pending = []
    if pending:
        Lead.objects.using(alias).bulk_update(pending, ["company"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("crm", "0020_zoominfo_company_contacts")]
    operations = [migrations.RunPython(group_companies, migrations.RunPython.noop)]
