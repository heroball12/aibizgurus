"""Conservative business grouping; ZoomInfo company IDs take precedence."""
import hashlib
import json
from urllib.parse import urlsplit

from .models import Lead


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
    from .ownership import claim_company, lead_data
    company = claim_company(lead_data(lead), lead.assigned_to, enforce=False)
    Lead.objects.filter(pk=lead.pk, company__isnull=True).update(company=company)
    lead.company = company
