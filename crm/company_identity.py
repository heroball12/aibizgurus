"""Stable business identities shared by imports, search and manual entry."""
import hashlib
import json
import re
import unicodedata
from urllib.parse import urlsplit


def normalized_name(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    value = re.sub(r"\b(incorporated|corporation|company|limited|inc|corp|llc|ltd)\b\.?", "", str(value or "").casefold())
    return re.sub(r"[^a-z0-9]", "", value)


def business_keys(data, provider_id=""):
    keys = []
    def add(kind, *parts):
        keys.append(hashlib.sha256(json.dumps([kind, *parts]).encode()).hexdigest())
    if provider_id:
        add("zoominfo", str(provider_id))
    website = str(data.get("website") or "").strip()
    try:
        domain = (urlsplit(website if "://" in website else "https://" + website).hostname or "").casefold().removeprefix("www.")
    except ValueError:
        domain = ""
    # Shared directory/social domains do not identify a business.
    shared = {"facebook.com", "instagram.com", "linkedin.com", "yelp.com", "google.com", "maps.google.com", "linktr.ee", "wixsite.com", "business.site"}
    name = normalized_name(data.get("business_name") or data.get("name"))
    if domain and "." in domain and not any(domain == host or domain.endswith("." + host) for host in shared):
        add("website", domain, name)
    city = normalized_name(data.get("city"))
    state = str(data.get("state") or "").casefold().strip()
    from .directory_locations import US_STATES
    state = next((code.lower() for code, label in US_STATES.items() if label.casefold() == state), state)
    if name and city and state:
        add("name-place", name, city, state)
    # Person phone numbers must not become company identities.
    phone = re.sub(r"\D", "", str(data.get("company_phone") or ""))
    if len(phone) == 11 and phone.startswith("1"):
        phone = phone[1:]
    if name and len(phone) >= 7:
        add("name-phone", name, phone)
    return list(dict.fromkeys(keys))
