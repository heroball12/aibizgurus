"""Conservative business grouping; ZoomInfo company IDs take precedence."""
import hashlib
import json
from urllib.parse import urlsplit

from .models import Company, Lead


def company_key(name, website="", city="", state=""):
    url = str(website or "").strip().lower()
    try:
        domain = urlsplit(url if "://" in url else "https://" + url).hostname or ""
    except ValueError:
        domain = ""
    domain = domain.removeprefix("www.")
    parts = [" ".join(str(s or "").casefold().split()) for s in (name, domain, city, state)]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def attach_company(lead):
    if lead.company_id or lead.lead_type != "internal_sales" or not lead.business_name.strip():
        return
    fields = {name: getattr(lead, name) for name in ("industry", "website", "address", "city", "state", "zip_code")}
    # A lead phone may belong to a person; only known business-only records supply an HQ number.
    fields["phone"] = lead.phone if not (lead.name or lead.point_of_contact) else ""
    fields["name"] = lead.business_name
    company, _ = Company.objects.get_or_create(
        match_key=company_key(lead.business_name, lead.website, lead.city, lead.state), defaults=fields,
    )
    Lead.objects.filter(pk=lead.pk, company__isnull=True).update(company=company)
    lead.company = company
