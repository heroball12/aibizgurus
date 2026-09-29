"""Business status from attributed public evidence, never from site uptime alone."""

import json
import re
from datetime import date
from urllib import request

from django.utils import timezone


def listing_closure(tags):
    """Only business lifecycle keys, not unrelated disused parking/building features."""
    for prefix in ("closed", "disused", "abandoned", "demolished", "removed", "razed"):
        if str(tags.get(prefix, "")).lower() == "yes":
            return f"Listing is marked {prefix}."
        for kind in ("shop", "amenity", "office", "craft", "healthcare", "tourism"):
            value = str(tags.get(f"{prefix}:{kind}", "")).lower()
            active = str(tags.get(kind, "")).lower()
            if (
                value
                and value != "no"
                and (not active or active in {value, "yes", "no", "vacant", "closed"})
            ):
                return f"Listing marks its {kind} as {prefix}."
    if str(tags.get("shop", "")).lower() in {"vacant", "closed", "no"}:
        return "Listing marks the shop as vacant or closed."
    for key in ("opening_hours", "opening_hours:covid19"):
        # Never confuse 'closed right now' or an old COVID exception with a permanent closure.
        if key == "opening_hours" and str(tags.get(key, "")).strip().lower() in {
            "closed",
            "off",
        }:
            return "Listing marks all opening hours as closed; review its operating status."
    end = str(tags.get("end_date", ""))
    try:
        ended = (
            date.fromisoformat(end) if len(end) == 10 else date(int(end), 12, 31)
        ) < timezone.localdate()
    except (ValueError, OverflowError):
        ended = False
    if ended:
        return "Listing has a past end date."
    return ""


def listing_verdict(tags, source):
    reason = listing_closure(tags)
    return {
        "status": "not_operating" if reason else "unverified",
        "checked_at": timezone.now().isoformat(),
        "label": (
            "Listing reports not operating" if reason else "Operating status unverified"
        ),
        "evidence": [
            {
                "source": source,
                "detail": reason
                or "A public listing exists; that alone does not confirm the business is still operating.",
            }
        ],
    }


def website_closure(page):
    # Restrict to prominent first-page copy, rather than unrelated articles or old footer links.
    for text in [page.title, page.description, *page.headings[:5]]:
        if re.search(
            r"\b(?:permanently closed|closed permanently|closed for good|ceased (?:all )?(?:trading|operations)|no longer (?:in business|operating)|we (?:have permanently closed|are permanently closed|have closed our doors))\b",
            text,
            re.I,
        ):
            return {
                "status": "needs_review",
                "detail": "Possible closure notice on the website: " + text[:220],
                "source": page.url,
            }
        if re.search(
            r"\b(?:temporarily closed|closed (?:until further notice|for the season))\b",
            text,
            re.I,
        ):
            return {
                "status": "needs_review",
                "detail": "Possible temporary closure notice: " + text[:220],
                "source": page.url,
            }
    return None


def verify_business(lead):
    """Refresh the actual OSM record and scan the public website. No Google key needed."""
    from .website_research import research_website
    from .public_site import SiteError

    source = getattr(lead, "source_url", "")
    if not source:
        source = (lead.business_verification or {}).get("listing_url", "")
    match = re.fullmatch(
        r"https://www\.openstreetmap\.org/(node|way|relation)/(\d+)", source
    )
    evidence, warnings = [], []
    state = "unverified"
    if match:
        url = f"https://api.openstreetmap.org/api/0.6/{match[1]}/{match[2]}.json"
        try:
            req = request.Request(
                url,
                headers={
                    "User-Agent": "AIBusinessGurusResearch/1.0 (+https://aibiz.guru)",
                    "Accept": "application/json",
                },
            )
            with request.urlopen(req, timeout=7) as response:
                data = json.loads(response.read(1_000_001))
            elements = data.get("elements", [])
            tags = elements[0].get("tags", {}) if elements else {}
            if not isinstance(tags, dict):
                raise ValueError()
            normalize = lambda text: re.sub(r"[^a-z0-9]", "", str(text).lower())
            reason = listing_closure(tags)
            if reason:
                state = "not_operating"
                evidence.append({"source": source, "detail": reason})
            elif tags.get("name") and normalize(tags["name"]) != normalize(
                lead.business_name
            ):
                state = "needs_review"
                evidence.append(
                    {
                        "source": source,
                        "detail": "This location's listing now has a different business name: "
                        + str(tags["name"])[:200],
                    }
                )
            else:
                evidence.append(
                    {
                        "source": source,
                        "detail": "No explicit closure found in the current directory record. This does not confirm continued operation.",
                    }
                )
        except (OSError, ValueError, AttributeError, TypeError, IndexError):
            warnings.append(
                "The current directory record could not be checked. Its removal or unavailability is not proof of closure."
            )
    report = None
    if lead.website:
        try:
            report = research_website(lead.website)
            notice = report.get("business_notice")
            if notice:
                if state != "not_operating":
                    state = "needs_review"
                evidence.append(
                    {"source": notice["source"], "detail": notice["detail"]}
                )
            else:
                evidence.append(
                    {
                        "source": report["pages"][0],
                        "detail": "Website is accessible with no prominent closure notice found. Website availability is not proof of an operating business.",
                    }
                )
        except SiteError as exc:
            warnings.append(
                str(exc) + " A website error does not prove the business is closed."
            )
    if not evidence:
        warnings.append(
            "No reliable current status evidence was available. Confirm directly before outreach."
        )
    labels = {
        "unverified": "Operating status unverified",
        "not_operating": "Listing reports not operating",
        "needs_review": "Closure / listing change needs review",
    }
    return {
        "status": state,
        "label": labels[state],
        "checked_at": timezone.now().isoformat(),
        "listing_url": source,
        "evidence": evidence,
        "warnings": warnings,
    }, report


def contact_blocked(lead):
    check = (
        lead.business_verification
        if isinstance(lead.business_verification, dict)
        else {}
    )
    return check.get("status") in {
        "not_operating",
        "needs_review",
        "confirmed_closed",
        "temporarily_closed",
    }


def merge_verification(previous, current):
    """An inconclusive automated recheck must not clear a direct confirmation or a closure flag."""
    previous = previous if isinstance(previous, dict) else {}
    if current.get("status") == "unverified" and previous.get("status") not in {
        None,
        "unverified",
    }:
        return {
            **previous,
            "rechecked_at": current.get("checked_at"),
            "warnings": [
                *current.get("warnings", []),
                "The latest public check was inconclusive. The earlier outcome remains in place; record a direct verification to change it.",
            ],
            "evidence": (previous.get("evidence", []) + current.get("evidence", []))[
                :8
            ],
        }
    return current
