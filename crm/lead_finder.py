from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from datetime import timedelta
import hashlib
import json
import logging
import math
import re
from urllib import parse, request, error
import socket

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from audit.utils import log_activity
from core.models import RequestBudget
from .models import Lead, LeadActivity, LeadGenerationBatch, LeadStaging
from .directory_locations import city_and_state, resolve_city

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DirectoryLead:
    business_name: str
    phone_number: str
    industry: str
    city: str = ""
    state: str = ""
    confidence_score: Decimal = Decimal("0.70")
    website: str = ""
    source_url: str = ""
    address: str = ""
    email: str = ""


def public_url(value):
    value = (value or "").strip()
    if value and "://" not in value:
        value = "https://" + value
    try:
        parsed = parse.urlsplit(value)
        host = parsed.hostname
        URLValidator(schemes=["http", "https"])(value)
    except (ValueError, ValidationError):
        return ""
    return (
        value[:200]
        if parsed.scheme in {"http", "https"}
        and host
        and not parsed.username
        and len(value) <= 200
        else ""
    )


class LeadProvider(ABC):
    """Provider interface for public business-listing sources."""

    name = "base"

    @abstractmethod
    def search(
        self, *, industry: str, location: str, limit: int
    ) -> list[DirectoryLead]:
        raise NotImplementedError


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def format_phone(value: str) -> str:
    digits = normalize_phone(value)
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return value.strip()


def normalize_business(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def lead_dedupe_key(
    *, business_name: str, phone_number: str, city: str = "", state: str = ""
) -> str:
    phone_digits = normalize_phone(phone_number)
    if len(phone_digits) >= 7:
        return f"phone:{phone_digits}"
    business = normalize_business(business_name)
    place = normalize_business(f"{city}{state}")
    return f"biz:{business}:{place}" if business else ""


def split_location(location: str) -> tuple[str, str]:
    return city_and_state(location)


class DirectoryError(RuntimeError):
    """A safe, actionable provider failure, suitable for the result screen."""

    def __init__(self, message, code="provider_unavailable"):
        super().__init__(message)
        self.code = code


def listing_email(value):
    value = (value or "").strip().removeprefix("mailto:")
    try:
        validate_email(value)
    except ValidationError:
        return ""
    return value if len(value) <= 254 else ""


class OpenStreetMapProvider(LeadProvider):
    """Optional public-data provider. It returns only the allowed fields."""

    name = "openstreetmap"

    INDUSTRY_FILTERS = {
        "cannabis": ['["shop"="cannabis"]'],
        "mortgage": ['["office"="financial"]["financial"="mortgage"]'],
        "restaurant": ['["amenity"="restaurant"]'],
        "dentist": ['["amenity"="dentist"]'],
        "law firm": ['["office"="lawyer"]'],
        "insurance": ['["office"="insurance"]'],
        "real estate": ['["office"="estate_agent"]'],
        "accounting": ['["office"="accountant"]'],
        "financial advisor": ['["office"="financial"]'],
        "chiropractor": ['["healthcare"="chiropractor"]'],
        "medical spa": ['["healthcare"="clinic"]["healthcare:speciality"="cosmetic"]'],
        "salon": ['["shop"="hairdresser"]'],
        "barbershop": ['["shop"="hairdresser"]'],
        "auto repair": ['["shop"="car_repair"]'],
        "car dealership": ['["shop"="car"]'],
        "roofing": ['["craft"="roofer"]'],
        "construction": ['["craft"="builder"]'],
        "hvac": ['["craft"="hvac"]'],
        "solar": ['["craft"="solar_panel_installer"]'],
        "home services": ['["craft"~"^(plumber|electrician|hvac|roofer|carpenter)$"]'],
    }

    ALIASES = {
        "restaurants": "restaurant",
        "dispensary": "cannabis",
        "cannabis dispensary": "cannabis",
        "plumber": "plumbing",
        "plumbers": "plumbing",
        "electricians": "electrician",
        "lawyer": "law firm",
        "lawyers": "law firm",
        "med spa": "medical spa",
        "hair salon": "salon",
        "dentists": "dentist",
        "roofers": "roofing",
    }

    def filters_for(self, industry):
        key = self.ALIASES.get(industry.strip().lower(), industry.strip().lower())
        filters = list(self.INDUSTRY_FILTERS.get(key, []))
        extras = {
            "restaurant": ['["amenity"="fast_food"]'],
            "cannabis": ['["shop"="chemist"]["name"~"cannabis|dispensary",i]'],
            "plumbing": ['["craft"="plumber"]'],
            "electrician": ['["craft"="electrician"]'],
            "landscaping": ['["craft"="gardener"]'],
            "medical spa": [
                '["name"~"med.?spa|medical spa",i][~"^(shop|healthcare|amenity|office)$"~"."]'
            ],
            "hvac": ['["craft"="air_conditioning"]', '["craft"="heating_engineer"]'],
        }
        filters.extend(extras.get(key, []))
        if not filters:
            # Literal name matching is a transparent fallback, not invented category data.
            filters = [
                f'["name"~{json.dumps(re.escape(industry.strip()))},i][~"^(shop|office|craft|amenity|healthcare)$"~"."]'
            ]
        return filters

    def _request_payload(self, endpoint, query, timeout):
        cooldown_key = (
            "lead-provider-cooldown:" + hashlib.sha256(endpoint.encode()).hexdigest()
        )
        cooldown = cache.get(cooldown_key)
        if cooldown:
            raise DirectoryError(
                "The directory is cooling down after an outage or rate limit. Wait a minute and retry this search.",
                "rate_limited" if cooldown == "rate_limited" else "cooldown",
            )
        # Overpass supports GET for these short, read-only public queries.
        separator = "&" if "?" in endpoint else "?"
        req = request.Request(
            endpoint + separator + parse.urlencode({"data": query}),
            headers={
                "User-Agent": "AI-Business-Gurus-LeadFinder/2.0 (+https://aibiz.guru)"
            },
        )
        try:
            with request.urlopen(req, timeout=timeout) as response:
                content = response.read(4_000_001)
                if len(content) > 4_000_000:
                    raise DirectoryError(
                        "The directory returned too much data. Search a smaller city or a more specific business category.",
                        "response_size",
                    )
                payload = json.loads(content.decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(
                payload.get("elements"), list
            ):
                raise ValueError("Invalid directory response")
        except error.HTTPError as exc:
            cache.set(
                cooldown_key,
                "rate_limited" if exc.code in {429, 406} else "unavailable",
                60,
            )
            if exc.code in {429, 406}:
                raise DirectoryError(
                    "The directory is rate-limiting searches. Wait a minute, then retry. Your existing results are saved.",
                    "rate_limited",
                ) from exc
            if exc.code == 504:
                raise DirectoryError(
                    "The directory is too busy to finish this search. Retry shortly or choose a smaller city.",
                    "provider_timeout",
                ) from exc
            raise DirectoryError(
                "The business directory is temporarily unavailable. Retry shortly; your existing results are saved."
            ) from exc
        except (TimeoutError, socket.timeout, error.URLError) as exc:
            cache.set(cooldown_key, "unavailable", 60)
            logger.warning("Lead directory connection failed: %s", type(exc).__name__)
            raise DirectoryError(
                "The business directory did not respond in time. Retry shortly; your existing results are saved.",
                "provider_timeout",
            ) from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise DirectoryError(
                "The directory returned an unreadable response. Retry shortly.",
                "invalid_response",
            ) from exc
        if payload.get("remark") and not any(
            isinstance(e, dict) and e.get("type") != "count"
            for e in payload["elements"]
        ):
            raise DirectoryError(
                "The directory timed out before returning listings.", "provider_timeout"
            )
        return payload

    def search(
        self, *, industry: str, location: str, limit: int
    ) -> list[DirectoryLead]:
        self.summary = {}
        if not getattr(settings, "LEAD_FINDER_ENABLE_PUBLIC_HTTP", False):
            raise DirectoryError(
                "Public search is disabled. Your administrator can enable LEAD_FINDER_ENABLE_PUBLIC_HTTP; spreadsheet imports still work.",
                "disabled",
            )
        try:
            city, state, latitude, longitude = resolve_city(location)
        except ValueError as exc:
            raise DirectoryError(str(exc), "location_not_found") from exc
        if not industry.strip():
            raise DirectoryError(
                "Choose an industry or enter a business keyword.", "industry"
            )
        # An Overpass slot can queue for 15 seconds before the query starts.
        # The HTTP deadline must leave room for that queue as well as execution.
        timeout = max(25, min(35, float(settings.LEAD_FINDER_PROVIDER_TIMEOUT)))
        query_timeout = max(10, int(timeout) - 15)
        endpoint = settings.LEAD_FINDER_OVERPASS_URL
        filters = self.filters_for(industry)
        # Local Census coordinates avoid slow remote area/relation lookups.
        # A bounding box uses the directory's spatial index directly. The
        # roughly 20x20-mile area may include nearby towns (shown in the UI).
        lat_delta = 10 / 69
        lon_delta = 10 / (69 * math.cos(math.radians(latitude)))
        west, east = (
            (value + 180) % 360 - 180
            for value in (longitude - lon_delta, longitude + lon_delta)
        )
        bounds = (
            f"{latitude-lat_delta:.5f},{west:.5f},{latitude+lat_delta:.5f},{east:.5f}"
        )
        union = "".join(f'nwr{f}["name"]({bounds});' for f in filters)
        query = f"[out:json][timeout:{query_timeout}];({union});out tags {min(2000, max(limit * 8, 100))};"
        fallback = getattr(settings, "LEAD_FINDER_OVERPASS_FALLBACK_URL", "")
        cache_key = (
            "lead-listings:v5:"
            + hashlib.sha256(
                json.dumps(
                    [endpoint, fallback, industry.lower(), city.lower(), state, limit]
                ).encode()
            ).hexdigest()
        )
        cached = cache.get(cache_key)
        if cached is not None:
            self.summary = {**cached[1], "cached": True}
            return cached[0]
        endpoints = list(dict.fromkeys([endpoint, fallback]))
        payload = None
        used_endpoint = endpoint
        failures = []
        for candidate_endpoint in filter(None, endpoints):
            try:
                payload = self._request_payload(candidate_endpoint, query, timeout)
                used_endpoint = candidate_endpoint
                break
            except DirectoryError as exc:
                failures.append(exc)
                if exc.code not in {
                    "provider_unavailable",
                    "provider_timeout",
                    "cooldown",
                }:
                    raise
        if payload is None:
            raise failures[-1]
        elements = payload["elements"]
        warning = (
            "The directory reached its time limit; these are the listings it returned before stopping."
            if payload.get("remark")
            else ""
        )
        leads = []
        missing_contact = 0
        for element in elements:
            if not isinstance(element, dict) or element.get("type") == "count":
                continue
            tags = element.get("tags") or {}
            if not isinstance(tags, dict):
                continue
            name = str(tags.get("name") or "").strip()
            raw_phone = (
                str(tags.get("phone") or tags.get("contact:phone") or "")
                .split(";")[0]
                .strip()
            )
            phone = (
                format_phone(raw_phone)
                if 7 <= len(normalize_phone(raw_phone)) <= 15
                else ""
            )
            website = public_url(
                str(tags.get("website") or tags.get("contact:website") or "")
            )
            email = listing_email(
                str(tags.get("email") or tags.get("contact:email") or "")
            )
            if (
                not name
                or tags.get("disused") == "yes"
                or tags.get("abandoned") == "yes"
            ):
                continue
            if not (phone or website or email):
                missing_contact += 1
                continue
            kind, osm_id = element.get("type"), element.get("id")
            source_url = (
                f"https://www.openstreetmap.org/{kind}/{osm_id}"
                if kind in {"node", "way", "relation"} and isinstance(osm_id, int)
                else ""
            )
            leads.append(
                DirectoryLead(
                    business_name=name[:200],
                    phone_number=phone[:80],
                    industry=industry,
                    city=str(tags.get("addr:city") or f"Near {city}, {state}")[:120],
                    state=str(tags.get("addr:state") or "")[:80],
                    confidence_score=Decimal("0.82") if phone else Decimal("0.60"),
                    website=website,
                    email=email,
                    source_url=source_url,
                    address=" ".join(
                        str(tags.get(k) or "")
                        for k in ["addr:housenumber", "addr:street"]
                    ).strip()[:255],
                )
            )
        leads.sort(
            key=lambda lead: (
                not bool(lead.phone_number),
                not bool(lead.website),
                lead.business_name.lower(),
            )
        )
        self.summary = {
            "host": parse.urlsplit(used_endpoint).hostname,
            "failover": used_endpoint != endpoint,
            "listings_checked": sum(
                1 for e in elements if isinstance(e, dict) and e.get("type") != "count"
            ),
            "missing_contact": missing_contact,
            "warning": warning,
            "location": f"{city}, {state}",
            "area_width_miles": 20,
            "cached": False,
        }
        if warning and not leads:
            raise DirectoryError(
                "The directory timed out before returning usable listings. Retry or choose a smaller city.",
                "provider_timeout",
            )
        cache.set(cache_key, (leads[:limit], self.summary), 300)
        return leads[:limit]


def get_lead_providers() -> list[LeadProvider]:
    return [OpenStreetMapProvider()]


@transaction.atomic
def create_generation_batch(
    *, employee, industry: str, location: str, quantity: int
) -> LeadGenerationBatch:
    lock = f"lead-search-create:{employee.pk}"
    RequestBudget.objects.get_or_create(
        key=lock, defaults={"expires_at": timezone.now() + timedelta(days=36500)}
    )
    RequestBudget.objects.select_for_update().get(pk=lock)
    existing = LeadGenerationBatch.objects.filter(
        employee=employee,
        industry__iexact=industry,
        location__iexact=location,
        quantity_requested=quantity,
        status__in=["queued", "generating", "searching", "saving"],
        created_at__gte=timezone.now() - timedelta(minutes=3),
    ).first()
    if existing:
        return existing
    return LeadGenerationBatch.objects.create(
        employee=employee,
        industry=industry,
        location=location,
        quantity_requested=quantity,
        status="queued",
        status_message="Queued for generation.",
    )


def set_batch_status(
    batch: LeadGenerationBatch, status: str, progress: int, message: str = ""
):
    batch.status = status
    batch.progress_percent = max(0, min(100, progress))
    if message:
        batch.status_message = message[:255]
    batch.save(update_fields=["status", "progress_percent", "status_message"])


def duplicate_exists(
    candidate: DirectoryLead, dedupe_key: str, *, exclude_staging_id=None
) -> bool:
    if not dedupe_key:
        return True
    phone = candidate.phone_number
    existing_staging = (
        LeadStaging.objects.filter(dedupe_key=dedupe_key)
        .exclude(batch__provider_summary__has_key="fallback_directory")
        .exclude(pk=exclude_staging_id)
        .exists()
    )
    if existing_staging:
        return True
    matches = Q(duplicate_key=dedupe_key)
    if phone:
        matches |= Q(phone=phone)
    if candidate.city and not phone:
        matches |= Q(
            business_name__iexact=candidate.business_name,
            city__iexact=candidate.city,
            state__iexact=candidate.state,
        )
    digits = normalize_phone(phone)
    if len(digits) >= 7:
        matches |= Q(
            phone__regex=(r"^\D*(1\D*)?" if len(digits) == 10 else r"^\D*")
            + r"\D*".join(digits)
            + r"\D*$"
        )
    return Lead.objects.filter(lead_type="internal_sales").filter(matches).exists()


def generate_leads_for_batch(
    batch_id: int, providers: list[LeadProvider] | None = None
) -> LeadGenerationBatch:
    with transaction.atomic():
        batch = (
            LeadGenerationBatch.objects.select_for_update(of=("self",))
            .select_related("employee")
            .get(pk=batch_id)
        )
        if batch.status in {"completed", "generating", "searching", "saving"}:
            return batch
        started = timezone.now()
        batch.started_at = started
        batch.status = "generating"
        batch.progress_percent = 5
        batch.status_message = "Starting real business listing search."
        batch.save(
            update_fields=["started_at", "status", "progress_percent", "status_message"]
        )

    provider_counts = {}
    seen_batch_keys = set(
        LeadStaging.objects.filter(batch=batch)
        .exclude(dedupe_key="")
        .values_list("dedupe_key", flat=True)
    )
    duplicate_count = batch.duplicates_removed or 0
    created_count = batch.staged_leads.count()
    providers = get_lead_providers() if providers is None else providers

    try:
        set_batch_status(batch, "searching", 18, "Searching public business listings.")
        for provider in providers:
            remaining = max(batch.quantity_requested - created_count, 0)
            if remaining <= 0:
                break
            provider_results = provider.search(
                industry=batch.industry,
                location=batch.location,
                limit=max(remaining * 2, remaining),
            )
            provider_counts[provider.name] = len(provider_results)
            provider_counts["directory"] = getattr(provider, "summary", {})
            for result in provider_results:
                if not result.business_name or not (
                    result.phone_number or result.website or result.email
                ):
                    continue
                key = lead_dedupe_key(
                    business_name=result.business_name,
                    phone_number=result.phone_number,
                    city=result.city,
                    state=result.state,
                )
                if key in seen_batch_keys:
                    duplicate_count += 1
                    continue
                seen_batch_keys.add(key)
                with transaction.atomic():
                    RequestBudget.objects.get_or_create(
                        key="lead-staging-write-lock",
                        defaults={"expires_at": timezone.now() + timedelta(days=36500)},
                    )
                    RequestBudget.objects.select_for_update().get(
                        pk="lead-staging-write-lock"
                    )
                    if duplicate_exists(result, key):
                        duplicate_count += 1
                        if duplicate_count == 1 or duplicate_count % 10 == 0:
                            batch.duplicates_removed = duplicate_count
                            batch.status_message = f"Skipped {duplicate_count} duplicate lead{'' if duplicate_count == 1 else 's'}."
                            batch.save(
                                update_fields=["duplicates_removed", "status_message"]
                            )
                        continue

                    if created_count == 0 or created_count % 5 == 0:
                        set_batch_status(
                            batch,
                            "saving",
                            min(
                                95,
                                22
                                + round(
                                    (created_count / max(batch.quantity_requested, 1))
                                    * 70
                                ),
                            ),
                            f"Saving fresh leads as they come in from {provider.name}.",
                        )
                    LeadStaging.objects.create(
                        batch=batch,
                        business_name=result.business_name[:200],
                        phone_number=result.phone_number[:80],
                        industry=result.industry[:150],
                        city=result.city[:120],
                        state=result.state[:80],
                        email=listing_email(result.email),
                        website=public_url(result.website),
                        source_url=public_url(result.source_url),
                        address=result.address[:255],
                        confidence_score=result.confidence_score,
                        dedupe_key=key,
                        created_by=batch.employee,
                    )
                created_count += 1
                if (
                    created_count == 1
                    or created_count % 5 == 0
                    or created_count >= batch.quantity_requested
                ):
                    batch.quantity_generated = created_count
                    batch.duplicates_removed = duplicate_count
                    batch.progress_percent = min(
                        95,
                        25
                        + round(
                            (created_count / max(batch.quantity_requested, 1)) * 70
                        ),
                    )
                    batch.status = "saving"
                    batch.status_message = f"Generated {created_count}/{batch.quantity_requested} fresh lead{'' if created_count == 1 else 's'}."
                    batch.save(
                        update_fields=[
                            "quantity_generated",
                            "duplicates_removed",
                            "progress_percent",
                            "status",
                            "status_message",
                        ]
                    )
                if created_count >= batch.quantity_requested:
                    break

        completed = timezone.now()
        batch.refresh_from_db()
        batch.status = "completed"
        batch.progress_percent = 100
        batch.quantity_generated = created_count
        batch.duplicates_removed = duplicate_count
        batch.completed_at = completed
        batch.duration_seconds = Decimal(
            str(round((completed - started).total_seconds(), 2))
        )
        if created_count:
            batch.status_message = f"Found {created_count} new businesses. Check the available phone, email and website on each result."
        elif duplicate_count:
            batch.status_message = f"Found listings, but all {duplicate_count} matches are already in the CRM or saved results. Try another city or review your pipeline."
        else:
            batch.status_message = "No businesses with public contact details matched this city and industry. Try another category, a business keyword, or a nearby city."
        provider_counts["contacts"] = {
            "phone": batch.staged_leads.exclude(phone_number="").count(),
            "website": batch.staged_leads.exclude(website="").count(),
            "email": batch.staged_leads.exclude(email="").count(),
        }
        batch.provider_summary = provider_counts
        batch.save(
            update_fields=[
                "status",
                "progress_percent",
                "quantity_generated",
                "duplicates_removed",
                "completed_at",
                "duration_seconds",
                "status_message",
                "provider_summary",
            ]
        )
        log_activity(
            user=batch.employee,
            action="create",
            model_label="crm.LeadGenerationBatch",
            object_id=batch.pk,
            object_repr=str(batch),
            message=f"{batch.employee.get_full_name() or batch.employee.username if batch.employee else 'System'} generated {created_count} {batch.industry} leads.",
            metadata={
                "industry": batch.industry,
                "location": batch.location,
                "quantity_requested": batch.quantity_requested,
                "quantity_generated": created_count,
                "duplicates_removed": duplicate_count,
                "duration_seconds": str(batch.duration_seconds),
                "providers": provider_counts,
            },
        )
    except Exception as exc:
        logger.exception("Lead generation batch %s failed", batch.pk)
        completed = timezone.now()
        batch.status = "failed"
        batch.completed_at = completed
        batch.duration_seconds = Decimal(
            str(round((completed - started).total_seconds(), 2))
        )
        provider_counts["error_code"] = getattr(exc, "code", "search_failed")
        batch.quantity_generated = created_count
        batch.duplicates_removed = duplicate_count
        batch.status_message = (
            str(exc)[:255]
            if isinstance(exc, RuntimeError)
            else "Search failed. Please try again or contact your administrator."
        )
        batch.provider_summary = provider_counts
        batch.save(
            update_fields=[
                "status",
                "completed_at",
                "duration_seconds",
                "status_message",
                "provider_summary",
                "quantity_generated",
                "duplicates_removed",
            ]
        )
        log_activity(
            user=batch.employee,
            action="other",
            model_label="crm.LeadGenerationBatch",
            object_id=batch.pk,
            object_repr=str(batch),
            message=f"Lead generation failed for {batch.industry}.",
            metadata={"error": exc.__class__.__name__, "providers": provider_counts},
        )
    return batch


def enqueue_generation_batch(batch: LeadGenerationBatch) -> bool:
    try:
        if not getattr(settings, "CELERY_BROKER_URL", ""):
            raise RuntimeError("Celery broker is not configured.")
        from .tasks import process_lead_generation_batch

        async_result = process_lead_generation_batch.delay(batch.pk)
        summary = dict(batch.provider_summary or {})
        summary["celery_task_id"] = getattr(async_result, "id", "")
        batch.provider_summary = summary
        batch.status_message = "Queued for background generation."
        batch.save(update_fields=["provider_summary", "status_message"])
        return True
    except Exception as exc:
        batch.status = "failed"
        batch.status_message = "The background queue is unavailable. Try a search of 20 or fewer, or ask your administrator to restore the worker."
        summary = dict(batch.provider_summary or {})
        summary["queue_warning"] = exc.__class__.__name__
        batch.provider_summary = summary
        batch.save(update_fields=["status", "status_message", "provider_summary"])
        return False


def convert_staging_to_crm_lead(
    staging: LeadStaging, *, employee, notes: str = "", contacted: bool = True
) -> Lead:
    if staging.batch.is_sample:
        raise ValueError(
            "This older batch contains generated sample data and cannot be used for real outreach. Start a new public-listing search."
        )
    note_text = (
        notes
        or staging.notes
        or (
            "First contact attempted from Lead Finder."
            if contacted
            else "Saved from Lead Finder. No outreach recorded."
        )
    ).strip()
    now = timezone.now()
    with transaction.atomic():
        RequestBudget.objects.get_or_create(
            key="lead-staging-write-lock",
            defaults={"expires_at": timezone.now() + timedelta(days=36500)},
        )
        RequestBudget.objects.select_for_update().get(pk="lead-staging-write-lock")
        staging = LeadStaging.objects.select_for_update().get(pk=staging.pk)
        if (
            not (employee.is_superuser or employee.role in {"admin", "owner"})
            and staging.created_by_id != employee.pk
        ):
            raise ValueError(
                "This result was reassigned. Refresh your Lead Finder results."
            )
        candidate = DirectoryLead(
            business_name=staging.business_name,
            phone_number=staging.phone_number,
            industry=staging.industry,
            city=staging.city,
            state=staging.state,
        )
        key = lead_dedupe_key(
            business_name=staging.business_name,
            phone_number=staging.phone_number,
            city=staging.city,
            state=staging.state,
        )
        if duplicate_exists(candidate, key, exclude_staging_id=staging.pk):
            raise ValueError(
                "A matching business is already in the internal CRM or another search result. Review the existing record before outreach."
            )
        lead = Lead.objects.create(
            lead_type="internal_sales",
            business_name=staging.business_name,
            industry=staging.industry,
            phone=staging.phone_number,
            email=staging.email,
            city=staging.city,
            state=staging.state,
            website=staging.website,
            address=staging.address,
            source="Lead Finder",
            source_file=f"Lead Finder Batch #{staging.batch_id}",
            source_sheet=staging.batch.industry,
            status="attempted" if contacted else "new",
            lead_temperature="cold",
            notes=note_text,
            cleaned_notes=note_text,
            assigned_to=employee,
            imported_at=staging.created_at,
            last_contact_at=now if contacted else None,
            classification_confidence=staging.confidence_score,
            classification_source="manual",
            duplicate_key=key,
            lead_generation_batch=staging.batch,
        )
        LeadActivity.objects.create(
            lead=lead,
            user=employee,
            raw_note=note_text,
            cleaned_note=note_text,
            inferred_status=lead.status,
            lead_temperature="cold",
            confidence_score=staging.confidence_score,
            activity_type="call" if contacted else "manual_note",
            classification_source="manual",
            manually_reviewed=True,
            metadata={
                "lead_generation_batch_id": staging.batch_id,
                "lead_staging_id": staging.pk,
                "source_url": staging.source_url,
            },
        )
        staging.delete()
    log_activity(
        user=employee,
        action="create",
        model_label="crm.Lead",
        object_id=lead.pk,
        object_repr=str(lead),
        message=(
            "Moved Lead Finder result into CRM after contact."
            if contacted
            else "Saved Lead Finder result to the pipeline without recording contact."
        ),
        metadata={"lead_generation_batch_id": lead.lead_generation_batch_id},
    )
    return lead
