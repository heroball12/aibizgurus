from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from datetime import timedelta
import hashlib
import json
import logging
import math
import re
from urllib import parse, request, error
import socket
import uuid

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
    business_verification: dict = field(default_factory=dict)


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

    def __init__(self, endpoint=None):
        # A browser step uses just one endpoint. CLI callers can still use
        # search() directly with the configured failover pair.
        self.endpoint = endpoint

    @staticmethod
    def endpoints():
        return list(dict.fromkeys(filter(None, [
            settings.LEAD_FINDER_OVERPASS_URL,
            getattr(settings, "LEAD_FINDER_OVERPASS_FALLBACK_URL", ""),
        ])))

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
        "insurance agent": "insurance",
        "insurance agents": "insurance",
        "insurance agency": "insurance",
    }

    def filters_for(self, industry):
        key = self.ALIASES.get(industry.strip().lower(), industry.strip().lower())
        filters = list(self.INDUSTRY_FILTERS.get(key, []))
        extras = {
            "insurance": ['["shop"="insurance"]'],
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
            cache.set(cooldown_key, "unavailable", 60)
            raise DirectoryError(
                "The directory returned an unreadable response. Retry shortly.",
                "invalid_response",
            ) from exc
        if payload.get("remark") and not any(
            isinstance(e, dict) and e.get("type") != "count"
            for e in payload["elements"]
        ):
            cache.set(cooldown_key, "unavailable", 60)
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
        # Small explicit memory reservations are admitted more readily by
        # shared Overpass instances. Don't occupy a web worker through a long
        # public queue: the next persisted step can try the backup instead.
        timeout = max(5, min(12, float(settings.LEAD_FINDER_PROVIDER_TIMEOUT)))
        query_timeout = min(8, int(timeout) - 2)
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
        query = f"[out:json][timeout:{query_timeout}][maxsize:33554432];({union});out tags 2000;"
        fallback = getattr(settings, "LEAD_FINDER_OVERPASS_FALLBACK_URL", "")
        cache_key = (
            "lead-listings:v7:"
            + hashlib.sha256(
                json.dumps(
                    [endpoint, fallback, filters, city.lower(), state]
                ).encode()
            ).hexdigest()
        )
        cached = cache.get(cache_key)
        if cached is not None:
            self.summary = {**cached[1], "cached": True}
            return cached[0]
        endpoints = [self.endpoint] if self.endpoint else self.endpoints()
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
                    "rate_limited",
                    "invalid_response",
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
        closed_count = 0
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
            from .business_status import listing_closure, listing_verdict

            if listing_closure(tags):
                closed_count += 1
                continue
            if not name:
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
                    business_verification={
                        **listing_verdict(tags, source_url),
                        "listing_url": source_url,
                    },
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
            "closed_excluded": closed_count,
            "warning": warning,
            "location": f"{city}, {state}",
            "area_width_miles": 20,
            "cached": False,
            "result_limit_reached": len(elements) >= 2000,
        }
        if warning and not leads:
            raise DirectoryError(
                "The directory timed out before returning usable listings. Retry or choose a smaller city.",
                "provider_timeout",
            )
        # Keep all candidates until CRM deduplication; slicing here hid fresh
        # businesses whenever the first page was already saved by the team.
        if not warning:
            cache.set(cache_key, (leads, self.summary), 300 if leads else 60)
        return leads


def get_lead_providers() -> list[LeadProvider]:
    return [OpenStreetMapProvider(endpoint) for endpoint in OpenStreetMapProvider.endpoints()]


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


LEASE_SECONDS = 45
SAVE_CHUNK_SIZE = 100
RETRYABLE_DIRECTORY_ERRORS = {
    "provider_unavailable", "provider_timeout", "cooldown", "rate_limited", "invalid_response",
}


def _finish_batch(batch, *, error=None):
    now = timezone.now()
    batch.status = "failed" if error else "completed"
    batch.progress_percent = 100
    batch.completed_at = now
    batch.duration_seconds = Decimal(str(round((now - (batch.started_at or now)).total_seconds(), 2)))
    batch.quantity_generated = batch.staged_leads.count()
    summary = dict(batch.provider_summary or {})
    summary["contacts"] = {
        "phone": batch.staged_leads.exclude(phone_number="").count(),
        "website": batch.staged_leads.exclude(website="").count(),
        "email": batch.staged_leads.exclude(email="").count(),
    }
    if error:
        summary["error_code"] = getattr(error, "code", "search_failed")
        batch.status_message = str(error)[:255] if isinstance(error, DirectoryError) else "Search could not finish. Any saved results are available below. Please retry shortly."
    elif batch.quantity_generated:
        batch.status_message = f"Found {batch.quantity_generated} new businesses. Check the available phone, email and website on each result."
    elif batch.duplicates_removed:
        batch.status_message = f"Found listings, but all {batch.duplicates_removed} matches are already in the CRM or saved results. Review your pipeline or choose another city."
    else:
        batch.status_message = "City confirmed. This public directory has no usable contact listings for this category in the search area. Try a related category or a nearby city."
    batch.provider_summary = summary
    # Candidate data is only a short-lived checkpoint, not another lead store.
    batch.search_state = {}
    batch.run_token = None
    batch.lease_expires_at = None
    batch.save()
    log_activity(
        user=batch.employee, action="other" if error else "create",
        model_label="crm.LeadGenerationBatch", object_id=batch.pk, object_repr=str(batch),
        message=f"Lead search {'failed' if error else 'completed'} for {batch.industry}: {batch.quantity_generated} new businesses.",
        metadata={"location": batch.location, "quantity_generated": batch.quantity_generated,
                  "duplicates_removed": batch.duplicates_removed, "providers": summary},
    )
    return batch


def _save_candidate_chunk(batch):
    """Called with the batch locked. Each chunk commits together, or not at all."""
    state = dict(batch.search_state)
    candidates = state.get("candidates", [])
    offset = int(state.get("offset", 0))
    stop = min(offset + SAVE_CHUNK_SIZE, len(candidates))
    RequestBudget.objects.get_or_create(
        key="lead-staging-write-lock",
        defaults={"expires_at": timezone.now() + timedelta(days=36500)},
    )
    RequestBudget.objects.select_for_update().get(pk="lead-staging-write-lock")
    count = batch.staged_leads.count()
    for raw in candidates[offset:stop]:
        if count >= batch.quantity_requested:
            break
        result = DirectoryLead(**raw)
        if not result.business_name or not (result.phone_number or result.website or result.email):
            continue
        key = lead_dedupe_key(business_name=result.business_name, phone_number=result.phone_number,
                              city=result.city, state=result.state)
        if duplicate_exists(result, key):
            batch.duplicates_removed += 1
            continue
        LeadStaging.objects.create(
            batch=batch, business_name=result.business_name[:200], phone_number=result.phone_number[:80],
            industry=result.industry[:150], city=result.city[:120], state=result.state[:80],
            email=listing_email(result.email), website=public_url(result.website),
            source_url=public_url(result.source_url), business_verification=result.business_verification,
            address=result.address[:255], confidence_score=result.confidence_score,
            dedupe_key=key, created_by=batch.employee,
        )
        count += 1
    batch.quantity_generated = count
    if count >= batch.quantity_requested or stop >= len(candidates):
        return _finish_batch(batch)
    state["offset"] = stop
    batch.search_state = state
    batch.progress_percent = 55 + round(40 * stop / max(len(candidates), 1))
    batch.status_message = f"Checked {stop} of {len(candidates)} contacts; {count} new businesses saved."
    batch.run_token = None
    batch.lease_expires_at = None
    batch.save()
    return batch


def advance_lead_generation_batch(batch_id, providers=None):
    """One bounded network attempt OR one DB chunk per request.

    The lease is persisted in Postgres (not process-local cache). A second tab
    cannot start the same step. A killed worker can be replaced after expiry;
    late responses must match the current token before they can save anything.
    """
    providers = get_lead_providers() if providers is None else providers
    with transaction.atomic():
        batch = LeadGenerationBatch.objects.select_for_update(of=("self",)).get(pk=batch_id)
        if not batch.can_advance:
            return batch
        state = dict(batch.search_state or {})
        if state.get("phase") == "saving":
            return _save_candidate_chunk(batch)
        index = int(state.get("provider_index", 0))
        attempts = int(state.get("attempts", 0))
        if attempts >= len(providers) + 2 or index >= len(providers):
            return _finish_batch(batch, error=DirectoryError(
                "The public directory is unavailable after several attempts. Saved results are safe. Please retry in a minute.",
                "provider_timeout",
            ))
        token = uuid.uuid4()
        batch.run_token = token
        batch.lease_expires_at = timezone.now() + timedelta(seconds=LEASE_SECONDS)
        batch.started_at = batch.started_at or timezone.now()
        batch.search_state = {"phase": "searching", "provider_index": index, "attempts": attempts + 1}
        batch.status = "searching"
        batch.progress_percent = 15 if index == 0 else 35
        batch.status_message = "Searching public business listings." if index == 0 else "Trying the backup directory after a slow or unavailable response."
        batch.save()
    provider = providers[index]
    try:
        results = provider.search(industry=batch.industry, location=batch.location, limit=2000)
        candidates = []
        for result in results[:2000]:
            record = asdict(result)
            record["confidence_score"] = str(result.confidence_score)
            candidates.append(record)
    except Exception as exc:
        logger.warning("Lead search %s attempt %s failed: %s", batch_id, index + 1, type(exc).__name__)
        with transaction.atomic():
            batch = LeadGenerationBatch.objects.select_for_update(of=("self",)).get(pk=batch_id)
            if batch.run_token != token:
                return batch
            if isinstance(exc, DirectoryError) and exc.code in RETRYABLE_DIRECTORY_ERRORS and index + 1 < len(providers):
                summary = dict(batch.provider_summary or {})
                summary.setdefault("attempts", []).append({"provider": provider.name, "error_code": exc.code})
                batch.provider_summary = summary
                batch.search_state = {**batch.search_state, "provider_index": index + 1}
                batch.run_token = None
                batch.lease_expires_at = None
                batch.status_message = "The first directory is busy. Continuing with the backup; no need to restart."
                batch.progress_percent = 30
                batch.save()
                return batch
            return _finish_batch(batch, error=exc)
    with transaction.atomic():
        batch = LeadGenerationBatch.objects.select_for_update(of=("self",)).get(pk=batch_id)
        if batch.run_token != token:
            return batch
        summary = dict(batch.provider_summary or {})
        summary.update({provider.name: len(candidates), "directory": getattr(provider, "summary", {})})
        batch.provider_summary = summary
        batch.run_token = None
        batch.lease_expires_at = None
        if not candidates:
            return _finish_batch(batch)
        batch.search_state = {"phase": "saving", "candidates": candidates, "offset": 0}
        batch.status = "saving"
        batch.progress_percent = 55
        batch.status_message = f"Found {len(candidates)} contacts. Checking for existing leads and saving new businesses."
        batch.save()
        return batch


def generate_leads_for_batch(batch_id, providers=None):
    """Worker/CLI wrapper; browser requests call advance once instead."""
    providers = get_lead_providers() if providers is None else providers
    # Bounded by two endpoints, two recovery attempts, and 20 save chunks.
    for _ in range(25):
        batch = advance_lead_generation_batch(batch_id, providers=providers)
        if not batch.can_advance:
            return batch
    return batch

def enqueue_generation_batch(batch: LeadGenerationBatch) -> bool:
    try:
        if not getattr(settings, "CELERY_BROKER_URL", ""):
            raise RuntimeError("Celery broker is not configured.")
        from .tasks import process_lead_generation_batch

        async_result = process_lead_generation_batch.delay(batch.pk)
        # A fast worker can already have finished. Merge only queue metadata
        # under the row lock instead of overwriting its new result summary.
        with transaction.atomic():
            batch = LeadGenerationBatch.objects.select_for_update(of=("self",)).get(pk=batch.pk)
            summary = dict(batch.provider_summary or {})
            summary["celery_task_id"] = getattr(async_result, "id", "")
            batch.provider_summary = summary
            if batch.status == "queued":
                batch.status_message = "Queued for background generation."
            batch.save(update_fields=["provider_summary", "status_message"])
        return True
    except Exception as exc:
        with transaction.atomic():
            batch = LeadGenerationBatch.objects.select_for_update(of=("self",)).get(pk=batch.pk)
            if batch.status != "queued":
                return batch.status != "failed"
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
        from .business_status import contact_blocked

        if contact_blocked(staging):
            raise ValueError(
                "This business has closure or listing-change evidence. Verify it directly and record the outcome before adding it to the pipeline."
            )
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
            website_review=staging.website_review,
            business_verification=staging.business_verification,
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
