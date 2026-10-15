"""Lossless ZoomInfo PERSON exports, with conservative contact matching."""
import hashlib
import json
import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email
from django.db.models import Q
from django.utils import timezone

from .models import Company, Lead, LeadZoomInfoProfile


def key(value):
    return re.sub(r"[\s-]+", "_", str(value or "").strip().lower())


def normalized(raw):
    return {key(k): str(v or "").strip() for k, v in raw.items()}


def is_zoominfo(headers):
    names = {key(h) for h in headers}
    return bool(names & {"zoominfo_contact_id", "zoominfo_contact_profile_url"}) or (
        "zoominfo_company_id" in names and {"first_name", "last_name"} <= names
    )


def value(row, *names):
    return next((row[key(n)] for n in names if row.get(key(n))), "")


def safe_url(text):
    if not text:
        return ""
    url = text if ":" in text else "https://" + text
    try:
        URLValidator(schemes=["http", "https"])(url)
    except ValidationError:
        return ""
    return url


def identity(raw):
    row = normalized(raw)
    contact_id = value(row, "ZoomInfo Contact ID")
    if contact_id:
        return "contact:" + contact_id
    # Exports without IDs still distinguish people at the same business.
    email = value(row, "Email Address", "Email").casefold()
    company = value(row, "ZoomInfo Company ID", "Company Name").casefold()
    name = " ".join(value(row, n).casefold() for n in ("First Name", "Middle Name", "Last Name")).strip()
    # Shared team mailboxes still belong to distinct named contacts.
    parts = [name, email, company]
    if not (name or email):
        parts = [json.dumps(raw, sort_keys=True, ensure_ascii=False)]
    return "fallback:" + hashlib.sha256("\0".join(parts).encode()).hexdigest()


def build_row(raw, row_number, source_sheet, errors):
    from .importers import ParsedLeadRow, sanitize_lead_data

    row = normalized(raw)
    for label in ("ZoomInfo Contact ID", "ZoomInfo Company ID"):
        if len(value(row, label)) > 120:
            errors.append(f"Row {row_number}: {label} is longer than 120 characters.")
            return None
    name = " ".join(filter(None, (value(row, n) for n in ("First Name", "Middle Name", "Last Name", "Suffix"))))
    email = value(row, "Email Address", "Email")
    try:
        validate_email(email)
    except ValidationError:
        email = ""  # The original cell is retained in the source profile.
    phone = value(row, "Direct Phone Number", "Direct Phone", "Mobile phone", "Mobile Phone Number", "Company HQ Phone")
    business = value(row, "Company Name")
    if not any((name, email, phone, business)):
        errors.append(f"Row {row_number}: ZoomInfo contact has no name, business, email, or phone.")
        return None
    blocked = any(value(row, n).casefold() in {"yes", "true", "1", "y"} for n in (
        "Do Not Call", "Do Not Contact", "Direct Phone Do Not Call", "Mobile Phone Do Not Call",
        "Direct Phone Number Do Not Call", "Mobile Phone Do Not Call Flag",
    ))
    data = sanitize_lead_data({
        "lead_type": "internal_sales", "name": name, "point_of_contact": name,
        "business_name": business, "email": email, "phone": phone,
        "contact_role": value(row, "Job Title"),
        "industry": value(row, "Primary Sub-Industry", "Primary Industry"),
        "website": safe_url(value(row, "Website")),
        # Never substitute a person's address for the company's location.
        "address": value(row, "Company Street Address"), "city": value(row, "Company City"),
        "state": value(row, "Company State"), "zip_code": value(row, "Company Zip Code"),
        "source": "ZoomInfo", "source_sheet": source_sheet,
        "status": "do_not_contact" if blocked else "new",
        "lead_temperature": "closed" if blocked else "cold",
        "notes": "", "cleaned_notes": "", "value": Decimal("0"),
        "assigned_to": None, "imported_at": timezone.now(),
        "classification_source": "import", "classification_confidence": Decimal("0"),
        "needs_review": False, "duplicate_key": "zoominfo:" + identity(raw),
    })
    return ParsedLeadRow(row_number, source_sheet, data, raw=dict(raw), source_format="zoominfo")


def find_match(row, *, lock=False):
    """Company/website/HQ phone alone must never merge two different people."""
    profiles = LeadZoomInfoProfile.objects.select_related("lead")
    if lock:
        profiles = profiles.select_for_update()
    contact_id = value(normalized(row.raw), "ZoomInfo Contact ID")
    lookup = Q(identity_key=identity(row.raw))
    if contact_id:
        lookup |= Q(contact_id=contact_id)
    profile = profiles.filter(lookup).first()
    if profile:
        return profile.lead
    email = row.data.get("email", "")
    if not email:
        return None
    candidates = Lead.objects.filter(lead_type="internal_sales", email__iexact=email)
    # A shared mailbox is not permission to merge known, different contacts.
    if contact_id:
        candidates = candidates.filter(Q(zoominfo_profile__isnull=True) | Q(zoominfo_profile__contact_id="") | Q(zoominfo_profile__contact_id=contact_id))
    if lock:
        candidates = candidates.select_for_update(of=("self",))
    matches = list(candidates[:2])
    if len(matches) != 1:
        return None
    existing = matches[0]
    old_name = (existing.point_of_contact or existing.name).strip().casefold()
    new_name = row.data.get("name", "").strip().casefold()
    if old_name and new_name and old_name != new_name:
        return None
    old_company = existing.business_name.strip().casefold()
    new_company = row.data.get("business_name", "").strip().casefold()
    if old_company and new_company and old_company != new_company:
        return None
    return existing


def merge_lead(existing, data):
    # The source profile can refresh; the salesperson's working fields win.
    fields = []
    for name in ("name", "point_of_contact", "business_name", "industry", "email", "phone", "website", "contact_role", "address", "city", "state", "zip_code", "source", "source_file", "source_sheet"):
        if not getattr(existing, name) and data.get(name):
            setattr(existing, name, data[name])
            fields.append(name)
    if existing.assigned_to_id is None and data.get("assigned_to") is not None:
        existing.assigned_to = data["assigned_to"]
        fields.append("assigned_to")
    if data.get("status") == "do_not_contact" and existing.status != "do_not_contact":
        existing.status, existing.lead_temperature = "do_not_contact", "closed"
        fields += ["status", "lead_temperature"]
    if fields:
        existing.save(update_fields=fields)


def save_profile(lead, row):
    profile, _ = LeadZoomInfoProfile.objects.get_or_create(lead=lead, defaults={"identity_key": identity(row.raw)})
    row_values = normalized(row.raw)
    # Preserve fields from earlier, wider exports and don't erase a populated cell with a blank.
    merged = dict(profile.data)
    previous_keys = {key(k): k for k in merged}
    for label, cell in row.raw.items():
        previous = previous_keys.get(key(label), label)
        if str(cell).strip() or previous not in merged:
            merged[previous] = cell
    profile.data = merged
    if value(row_values, "ZoomInfo Contact ID") or not profile.contact_id:
        profile.identity_key = identity(row.raw)
    profile.contact_id = value(row_values, "ZoomInfo Contact ID") or profile.contact_id
    profile.company_id = value(row_values, "ZoomInfo Company ID") or profile.company_id
    profile.save()
    company = company_for(row)
    if company and lead.company_id != company.pk:
        lead.company = company
        lead.save(update_fields=["company"])


def company_for(row):
    from .companies import company_key
    source = normalized(row.raw)
    company_id = value(source, "ZoomInfo Company ID")
    name = row.data.get("business_name", "")
    if not name and not company_id:
        return None
    fields = {"name": name or "Company " + company_id,
              **{field: row.data.get(field, "") for field in ("industry", "website", "address", "city", "state", "zip_code")},
              "phone": value(source, "Company HQ Phone")[:80],
              "country": value(source, "Company Country")[:120]}
    match_key = company_key(fields["name"], fields["website"], fields["city"], fields["state"])
    company = Company.objects.filter(zoominfo_id=company_id).first() if company_id else None
    if company is None:
        company = Company.objects.filter(match_key=match_key).first()
        if company and company_id and company.zoominfo_id not in (None, company_id):
            company = None  # Different external IDs are different businesses.
            match_key = None
        if company is None:
            if company_id:
                company, _ = Company.objects.get_or_create(zoominfo_id=company_id, defaults={**fields, "match_key": match_key})
            else:
                company, _ = Company.objects.get_or_create(match_key=match_key, defaults=fields)
    if company_id and not company.zoominfo_id:
        company.zoominfo_id = company_id
    for name, text in fields.items():
        if not getattr(company, name) and text:
            setattr(company, name, text)
    company_labels = {key(label) for _, labels in GROUPS[3:] + API_COMPANY_GROUPS for label in labels}
    company_data = dict(company.source_data)
    for label, text in row.raw.items():
        if key(label) in company_labels and (str(text or "").strip() or label not in company_data):
            company_data[label] = text
    company.source_data = company_data
    company.save()
    return company


GROUPS = [
    ("Contact & role", ["ZoomInfo Contact ID", "First Name", "Middle Name", "Last Name", "Salutation", "Suffix", "Job Title", "Management Level", "Job Start Date", "Job Function", "Department", "Company Division Name", "Highest Level of Education"]),
    ("Reach this contact", ["Direct Phone Number", "Email Address", "Email Domain", "Mobile phone", "Contact Accuracy Score", "Contact Accuracy Grade", "ZoomInfo Contact Profile URL", "LinkedIn Contact Profile URL", "Notice Provided Date"]),
    ("Contact location", ["Person Street", "Person City", "Person State", "Person Zip Code", "Country"]),
    ("Company", ["ZoomInfo Company ID", "Company Name", "Website", "Founded Year", "Company HQ Phone", "Fax", "Ticker", "Revenue (in 000s USD)", "Revenue Range (in USD)", "Employees", "Employee Range", "Ownership Type", "Business Model", "Number of Locations"]),
    ("Industry & classification", ["Primary Industry", "Primary Sub-Industry", "All Industries", "All Sub-Industries", "SIC Code 1", "SIC Code 2", "SIC Codes", "NAICS Code 1", "NAICS Code 2", "NAICS Codes", "Industry Hierarchical Category", "Secondary Industry Hierarchical Category"]),
    ("Company location", ["Company Street Address", "Company City", "Company State", "Company Zip Code", "Company Country", "Full Address"]),
    ("Company profiles & activity", ["ZoomInfo Company Profile URL", "LinkedIn Company Profile URL", "Facebook Company Profile URL", "Twitter Company Profile URL", "Alexa Rank", "Certified Active Company", "Certification Date"]),
    ("Funding", ["Total Funding Amount (in 000s USD)", "Recent Funding Amount (in 000s USD)", "Recent Funding Round", "Recent Funding Date", "Recent Investors", "All Investors"]),
]


API_COMPANY_GROUPS = [("Company API financials", ["Company Revenue (USD)", "Company Revenue (display)"]),
                      ("Company API source", ["ZoomInfo API company response"])]


def profile_context(lead):
    try:
        profile = lead.zoominfo_profile
    except LeadZoomInfoProfile.DoesNotExist:
        return {}
    remaining = {key(k): (k, v) for k, v in profile.data.items()}
    groups = []
    for title, labels in GROUPS:
        fields = [remaining.pop(key(label)) for label in labels if key(label) in remaining]
        if fields:
            groups.append({"title": title, "fields": fields})
    if remaining:
        groups.append({"title": "Other exported fields", "fields": list(remaining.values())})
    row = normalized(profile.data)
    phones = []
    blocked = lead.archived or lead.status in {"do_not_contact", "permanently_closed"}
    for label, name in (("Direct", "Direct Phone Number"), ("Mobile", "Mobile phone"), ("Company", "Company HQ Phone")):
        phone = value(row, name)
        if phone:
            dial = re.sub(r"[^\d+]", "", phone)
            phones.append({"label": label, "value": phone, "href": "tel:" + dial if dial and not blocked else ""})
    return {"zoominfo": profile, "zoominfo_groups": groups, "zoominfo_phones": phones}
