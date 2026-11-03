"""First assigned agent owns a company across every lead ingestion path."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.models import RequestBudget
from .company_identity import business_keys
from .models import Company, CompanyIdentity


class CompanyOwnedElsewhere(ValueError):
    def __init__(self, company):
        self.company = company
        super().__init__("Duplicate company: already assigned to another agent. The first owner's assignment has been kept.")


def lock_company_writes():
    # Shared with Finder promotion and sheet edits, always before record locks.
    key = "lead-staging-write-lock"
    RequestBudget.objects.get_or_create(key=key, defaults={"expires_at": timezone.now()+timedelta(days=36500)})
    RequestBudget.objects.select_for_update().get(pk=key)


def match_company(data, provider_id=""):
    keys = business_keys(data, provider_id)
    matches = {item.key: item.company for item in CompanyIdentity.objects.filter(key__in=keys).select_related("company")}
    return next((matches[key] for key in keys if key in matches), None)


def lead_data(lead):
    data = {key: getattr(lead, key) for key in ("business_name", "website", "industry", "address", "city", "state", "zip_code")}
    data["company_phone"] = lead.phone if not (lead.point_of_contact or lead.contact_role or (lead.name and lead.name != lead.business_name)) else ""
    return data


@transaction.atomic
def claim_company(data, assignee, *, provider_id="", enforce=True):
    from .companies import company_key
    if not data.get("business_name") and not provider_id:
        return None
    lock_company_writes()
    company = match_company(data, provider_id)
    if not company:
        match_key = company_key(data.get("business_name"), data.get("website"), data.get("city"), data.get("state"))
        company = Company.objects.filter(zoominfo_id=provider_id).first() if provider_id else None
        company = company or Company.objects.filter(match_key=match_key).first()
        if not company:
            company = Company.objects.create(
                name=data.get("business_name") or "Company " + provider_id,
                match_key=match_key, zoominfo_id=provider_id or None,
                **{key: data.get(key, "") for key in ("industry", "website", "address", "city", "state", "zip_code")},
                phone=data.get("company_phone", ""),
            )
    if enforce and company.owner_id and company.owner_id != getattr(assignee, "pk", None):
        raise CompanyOwnedElsewhere(company)
    if enforce:
        conflicts = CompanyIdentity.objects.filter(
            key__in=business_keys(data, provider_id), company__owner__isnull=False,
        ).exclude(company__owner_id=getattr(assignee, "pk", None)).select_related("company")
        conflict = conflicts.first()
        if conflict:
            raise CompanyOwnedElsewhere(conflict.company)
    if not company.owner_id and assignee:
        company.owner = assignee
        company.claimed_at = timezone.now()
        company.save(update_fields=["owner", "claimed_at"])
    for key in business_keys(data, provider_id):
        CompanyIdentity.objects.get_or_create(key=key, defaults={"company": company})
    return company


def search_data(kind, row):
    if kind == "public":
        return {**row, "company_phone": row.get("phone_number", "")}
    attrs = (row.get("raw") or {}).get("attributes") or {}
    company = attrs if kind == "companies" else attrs.get("company") or {}
    return {
        "business_name": row.get("company") or company.get("name") or row.get("name", ""),
        "website": row.get("website") or company.get("website", ""),
        "city": company.get("city", ""), "state": company.get("state", ""),
        "company_phone": company.get("phone", ""),
    }


def filter_owned_results(rows, user, kind):
    """Apply on every render as well as new searches; snapshots can become stale."""
    candidates = []
    for row in rows:
        provider_id = row.get("company_id") or (row.get("id") if kind == "companies" else "")
        candidates.append((row, business_keys(search_data(kind, row), provider_id)))
    keys = list({key for _, keys in candidates for key in keys})
    owners = {}
    for offset in range(0, len(keys), 500):
        owners.update(CompanyIdentity.objects.filter(key__in=keys[offset:offset+500]).values_list("key", "company__owner_id"))
    return [row for row, keys in candidates if not any(owners.get(key) and owners[key] != user.pk for key in keys)]
