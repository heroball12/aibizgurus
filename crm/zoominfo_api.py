"""ZoomInfo GTM API adapter. No browser tokens, legacy JWT flow, or automatic enrichment."""
import csv
import hashlib
import io
import json
import logging
import re
from threading import Lock

import requests
from django.conf import settings
from django.core.cache import cache
from django.views.decorators.debug import sensitive_variables
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from datetime import timezone as datetime_timezone

from .zoominfo_import import safe_url
from .zoominfo_errors import ZoomInfoError, OPERATIONS, http_error

BASE_URL = "https://api.zoominfo.com/gtm"
SCOPES = "api:data:company api:data:contact"
INTENT_SCOPES = "api:data:intent api:data:lookup"
TOKEN_LOCK = Lock()
logger = logging.getLogger(__name__)
MAX_SELECTION = 10
PAGE_SIZE = 25
# Field names from ZoomInfo's ContactEnrich OpenAPI schema, not search-result hints.
CONTACT_FIELDS = "id firstName middleName lastName salutation suffix email supplementalEmail phone mobilePhone directPhoneDoNotCall mobilePhoneDoNotCall jobTitle managementLevel jobFunction positionStartDate contactAccuracyScore street city state zipCode country externalUrls validDate lastUpdatedDate noticeProvidedDate personHasMoved isDefunct companyId companyName companyWebsite companyPhone companyStreet companyCity companyState companyZipCode companyCountry companyPrimaryIndustry companyIndustries companyEmployeeCount companyEmployeeRange companyRevenue companyRevenueNumeric companyRevenueRange companyType companyTicker companySocialMediaUrls companyDescription companyDivision companySicCodes companyNaicsCodes".split()


def configured():
    return bool(settings.ZOOMINFO_ENABLED and settings.ZOOMINFO_CLIENT_ID and settings.ZOOMINFO_CLIENT_SECRET)


@sensitive_variables()
def cache_key(suffix, *, intent=False):
    fingerprint = hashlib.sha256((settings.ZOOMINFO_CLIENT_ID + "\0" + settings.ZOOMINFO_CLIENT_SECRET + "\0" + (INTENT_SCOPES if intent else SCOPES)).encode()).hexdigest()
    return "zoominfo:" + fingerprint + ":" + suffix


@sensitive_variables()
def _request(method, path, *, paid=False, **kwargs):
    try:
        response = requests.request(method, BASE_URL + path, timeout=(3, 12), allow_redirects=False, **kwargs)
    except requests.Timeout:
        raise ZoomInfoError("The ZoomInfo request timed out.", operation=OPERATIONS.get(path, "ZoomInfo request"),
                            next_step="Try again later. The provider did not return a response within the connection/read timeout.", uncertain=paid) from None
    except requests.exceptions.SSLError:
        raise ZoomInfoError("A secure connection to ZoomInfo could not be established.", operation=OPERATIONS.get(path, "ZoomInfo request"),
                            next_step="Ask the owner to check server certificates and outbound HTTPS access.", uncertain=paid) from None
    except requests.RequestException:
        raise ZoomInfoError("The server could not communicate with ZoomInfo.", operation=OPERATIONS.get(path, "ZoomInfo request"),
                            next_step="Check server network/DNS access and ZoomInfo availability, then try again later.", uncertain=paid) from None
    status = response.status_code
    if not 200 <= status < 300:
        # Never log a response body, token, header, prospect data, or provider exception.
        logger.warning("ZoomInfo request failed: %s HTTP %s", path, status)
        raise http_error(response, path, kwargs, paid=paid)
    try:
        if len(response.content) > 4_000_000:
            raise ValueError("oversized")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("not an object")
    except (ValueError, TypeError):
        raise ZoomInfoError("ZoomInfo returned an unreadable response.", status=status, operation=OPERATIONS.get(path, "ZoomInfo request"),
                            next_step="The response was not a supported JSON object. Try later or contact ZoomInfo support if this continues.", uncertain=paid) from None
    return payload


@sensitive_variables()
def token(*, refresh=False, intent=False):
    if not settings.ZOOMINFO_ENABLED:
        raise ZoomInfoError("ZoomInfo API calls are disabled in this environment.", operation="Local configuration",
                            next_step="The owner can enable them with ZOOMINFO_ENABLED=1 in the server environment.")
    missing = [name for name in ("ZOOMINFO_CLIENT_ID", "ZOOMINFO_CLIENT_SECRET") if not getattr(settings, name)]
    if missing:
        raise ZoomInfoError("Missing server settings: " + ", ".join(missing) + ".", operation="Local configuration",
                            next_step="Add the missing settings in Render for the live site, or the private local .env for this preview. Render settings do not configure localhost.")
    with TOKEN_LOCK:
        key = cache_key("token", intent=intent)
        current = None if refresh else cache.get(key)
        if current:
            return current
        result = _request("POST", "/oauth/v1/token", auth=(settings.ZOOMINFO_CLIENT_ID, settings.ZOOMINFO_CLIENT_SECRET),
                          data={"grant_type": "client_credentials", "scope": INTENT_SCOPES if intent else SCOPES}, headers={"Accept": "application/json"})
        access = result.get("access_token")
        try:
            expires = int(result.get("expires_in", 0))
        except (ValueError, TypeError):
            expires = 0
        if not isinstance(access, str) or not access or expires <= 0:
            raise ZoomInfoError("ZoomInfo authentication returned an invalid token response.")
        cache.set(key, access, max(1, min(expires - 60, 3600)))
        return access


@sensitive_variables()
def call(method, path, *, paid=False, intent=False, **kwargs):
    access = token(intent=intent)
    headers = {"Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json", "Authorization": "Bearer " + access}
    try:
        return _request(method, path, paid=paid, headers=headers, **kwargs)
    except ZoomInfoError as exc:
        if getattr(exc, "status", None) != 401:
            raise
    # An explicit 401 did not enrich a record. Refresh once, never loop on paid calls.
    headers["Authorization"] = "Bearer " + token(refresh=True, intent=intent)
    return _request(method, path, paid=paid, headers=headers, **kwargs)


def output_fields(*, fresh=False):
    key = cache_key("contact-fields")
    fields = None if fresh else cache.get(key)
    if fields is not None:
        return fields
    payload = call("GET", "/data/v1/lookup/enrich", params={"filter[entity]": "contact", "filter[fieldType]": "output"})
    fields = []
    for item in resources(payload):
        attrs = item.get("attributes", {})
        name = attrs.get("fieldName")
        # Some accounts omit output accessGranted; absence is not proof of entitlement.
        if name in CONTACT_FIELDS and attrs.get("accessGranted") is not False:
            fields.append(name)
    fields = sorted(set(fields))
    if "id" not in fields:
        raise ZoomInfoError("ZoomInfo did not list the contact ID field. Ask ZoomInfo to confirm Data API contact enrichment access for this app.")
    cache.set(key, fields, 600)
    return fields


def resources(payload, *, paid=False):
    data = payload.get("data")
    if not isinstance(data, list) or any(not isinstance(item, dict) or not isinstance(item.get("attributes", {}), dict) for item in data):
        raise ZoomInfoError("ZoomInfo returned an unexpected data format.", uncertain=paid)
    return data


def valid_id(value):
    value = str(value or "")
    return value if re.fullmatch(r"[1-9][0-9]{0,17}", value) else ""


def search(kind, criteria, page=1):
    if kind not in {"companies", "people"}:
        raise ValueError("Invalid search kind")
    entity = "companies" if kind == "companies" else "contacts"
    resource_type = "CompanySearch" if kind == "companies" else "ContactSearch"
    payload = call("POST", f"/data/v1/{entity}/search", params={"page[number]": page, "page[size]": PAGE_SIZE},
                   json={"data": {"type": resource_type, "attributes": criteria}})
    rows = []
    for item in resources(payload):
        entity_id = valid_id(item.get("id"))
        if not entity_id:
            continue
        attrs = item.get("attributes", {})
        company = attrs if kind == "companies" else attrs.get("company", {})
        if not isinstance(company, dict):
            company = {}
        rows.append({"id": entity_id, "name": company.get("name", "") if kind == "companies" else " ".join(str(attrs.get(f) or "") for f in ("firstName", "middleName", "lastName")).strip(),
                     "title": attrs.get("jobTitle", ""), "company": company.get("name", ""),
                     "company_id": entity_id if kind == "companies" else valid_id(company.get("id")),
                     "website": safe_url(str(company.get("website") or "")),
                     "location": ", ".join(str(company.get(f) or "") for f in ("city", "state", "country") if company.get(f)),
                     "has_email": attrs.get("hasEmail") is True, "has_direct": attrs.get("hasDirectPhone") is True,
                     "has_mobile": attrs.get("hasMobilePhone") is True,
                     "dnc": attrs.get("directPhoneDoNotCall") is True or attrs.get("mobilePhoneDoNotCall") is True,
                     "raw": item})
    meta = payload.get("meta") or {}
    try:
        total = max(0, int(meta.get("totalResults", len(rows))))
    except (ValueError, TypeError, AttributeError):
        total = len(rows)
    links = payload.get("links") or {}
    has_next = (isinstance(links, dict) and bool(links.get("next"))) or page * PAGE_SIZE < total
    return rows, total, has_next


def enrich(ids, fields):
    return call("POST", "/data/v1/contacts/enrich", paid=True, json={"data": {"type": "ContactEnrich", "attributes": {
        "matchPersonInput": [{"personId": int(item)} for item in ids], "outputFields": fields,
        "requiredFields": ["id"],
    }}})


def intent_topics(*, fetch=False, fresh=False):
    key = cache_key("intent-topics", intent=True)
    topics = None if fresh else cache.get(key)
    if topics is not None or not fetch:
        return topics or []
    payload = call("GET", "/data/v1/lookup/intent-topics", intent=True)
    topics = []
    for item in resources(payload):
        attrs = item.get("attributes", {})
        name = attrs.get("name")
        if isinstance(name, str) and 0 < len(name) <= 300:
            topics.append((name, str(attrs.get("category") or "")))
    topics = sorted(set(topics))
    if not topics:
        raise ZoomInfoError("ZoomInfo returned no Intent topics. Ask ZoomInfo to confirm Intent API access for your app.")
    cache.set(key, topics, 3600)
    return topics


def intent_search(criteria, page=1):
    payload = call("POST", "/data/v1/intent/search", intent=True,
                   params={"page[number]": page, "page[size]": PAGE_SIZE, "sort": "-signalDate"},
                   json={"data": {"type": "IntentSearch", "attributes": criteria}})
    rows = []
    for item in resources(payload):
        attrs = item.get("attributes", {})
        company = attrs.get("company") or {}
        if not isinstance(company, dict):
            company = {}
        provider_id = str(item.get("id") or "")[:500]
        company_id = valid_id(company.get("id"))
        date = signal_datetime(attrs.get("signalDate"))
        score = attrs.get("signalScore")
        score = score if type(score) is int and 0 <= score <= 100 else None
        topic = str(attrs.get("topic") or "")[:300]
        website = safe_url(str(company.get("website") or ""))
        # Keep oversized URLs in the raw source, rather than truncating a working link.
        if len(website) > 200:
            website = ""
        # Never derive company identity from a recommended contact or opaque signal ID.
        fingerprint = hashlib.sha256((company_id + "\0" + provider_id).encode()).hexdigest()
        rows.append({"id": fingerprint, "provider_id": provider_id, "company_id": company_id,
                     "company": str(company.get("name") or "Company not supplied")[:200],
                     "website": website,
                     "topic": topic, "category": str(attrs.get("category") or "")[:300],
                     "signal_date": date.isoformat() if date else "", "score": score,
                     "audience_strength": str(attrs.get("audienceStrength") or "")[:20],
                     "saveable": bool(provider_id and company_id and date and score is not None and topic),
                     "raw": item})
    meta = payload.get("meta") or {}
    try:
        total = max(0, int(meta.get("totalResults", len(rows))))
    except (ValueError, TypeError, AttributeError):
        total = len(rows)
    links = payload.get("links") or {}
    return rows, total, (isinstance(links, dict) and bool(links.get("next"))) or page * PAGE_SIZE < total


def signal_datetime(value):
    try:
        date = parse_datetime(value) if isinstance(value, str) else None
    except ValueError:
        date = None
    if date and timezone.is_naive(date):
        date = timezone.make_aware(date, datetime_timezone.utc)
    return date


def text_cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


CONTACT_MAP = {"firstName": "First Name", "middleName": "Middle Name", "lastName": "Last Name", "salutation": "Salutation", "suffix": "Suffix", "email": "Email Address", "phone": "Direct Phone Number", "mobilePhone": "Mobile phone", "jobTitle": "Job Title", "managementLevel": "Management Level", "jobFunction": "Job Function", "positionStartDate": "Job Start Date", "contactAccuracyScore": "Contact Accuracy Score", "street": "Person Street", "city": "Person City", "state": "Person State", "zipCode": "Person Zip Code", "country": "Country", "noticeProvidedDate": "Notice Provided Date", "directPhoneDoNotCall": "Direct Phone Do Not Call", "mobilePhoneDoNotCall": "Mobile Phone Do Not Call"}
COMPANY_MAP = {"id": "ZoomInfo Company ID", "name": "Company Name", "website": "Website", "phone": "Company HQ Phone", "street": "Company Street Address", "city": "Company City", "state": "Company State", "zipCode": "Company Zip Code", "country": "Company Country", "primaryIndustry": "Primary Industry", "industries": "All Industries", "employeeCount": "Employees", "employeeRange": "Employee Range", "revenue": "Company Revenue (display)", "revenueNumeric": "Company Revenue (USD)", "revenueRange": "Revenue Range (in USD)", "type": "Ownership Type", "ticker": "Ticker", "division": "Company Division Name", "sicCodes": "SIC Codes", "naicsCodes": "NAICS Codes"}


def preview_csv(payload, selected_results):
    """Adapt full ID matches into the existing lossless preview; keep full raw responses."""
    selected = {row["id"]: row for row in selected_results}
    rows, skipped, seen = [], 0, set()
    for item in resources(payload, paid=True):
        meta = item.get("meta") or {}
        entity_id = valid_id(item.get("id"))
        if not isinstance(meta, dict) or not isinstance(meta.get("input", {}), dict):
            skipped += 1
            continue
        source_id = valid_id(meta.get("input", {}).get("personId"))
        if entity_id not in selected or (source_id and source_id != entity_id) or meta.get("matchStatus") != "FULL_MATCH" or entity_id in seen:
            skipped += 1
            continue
        seen.add(entity_id)
        attrs = item["attributes"]
        previous = selected[entity_id]["raw"].get("attributes", {})
        company = attrs.get("company") or previous.get("company") or {}
        if not isinstance(company, dict):
            skipped += 1
            continue
        row = {"ZoomInfo Contact ID": entity_id}
        for field, label in CONTACT_MAP.items():
            val = attrs.get(field, previous.get(field))
            if field in {"directPhoneDoNotCall", "mobilePhoneDoNotCall"}:
                val = attrs.get(field) is True or previous.get(field) is True
            if field == "managementLevel" and isinstance(val, list):
                val = ", ".join(str(x) for x in val)
            row[label] = text_cell(val)
        for field, label in COMPANY_MAP.items():
            value = company.get(field)
            if field in {"primaryIndustry", "industries"} and isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            row[label] = text_cell(value)
        # Metadata beyond our working CRM fields is retained verbatim as JSON.
        row["ZoomInfo API contact response"] = json.dumps(item, ensure_ascii=False)
        row["ZoomInfo API search result"] = json.dumps(selected[entity_id]["raw"], ensure_ascii=False)
        row["ZoomInfo API company response"] = json.dumps(company, ensure_ascii=False)
        row["Query Name"] = "ZoomInfo API"
        for profile in attrs.get("externalUrls") or []:
            if isinstance(profile, dict) and str(profile.get("type", "")).lower() == "linkedin":
                row["LinkedIn Contact Profile URL"] = text_cell(profile.get("url"))
        rows.append(row)
    if not rows:
        return b"", skipped
    headers = list(dict.fromkeys(k for row in rows for k in row))
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=headers)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig"), skipped
