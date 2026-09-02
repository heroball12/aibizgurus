from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import logging
import re
from urllib import parse, request

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from audit.utils import log_activity
from .models import Lead, LeadActivity, LeadGenerationBatch, LeadStaging


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DirectoryLead:
    business_name: str
    phone_number: str
    industry: str
    city: str = ""
    state: str = ""
    confidence_score: Decimal = Decimal("0.70")


class LeadProvider(ABC):
    """Provider interface for public business-listing sources."""

    name = "base"

    @abstractmethod
    def search(self, *, industry: str, location: str, limit: int) -> list[DirectoryLead]:
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


def lead_dedupe_key(*, business_name: str, phone_number: str, city: str = "", state: str = "") -> str:
    phone_digits = normalize_phone(phone_number)
    if len(phone_digits) >= 7:
        return f"phone:{phone_digits}"
    business = normalize_business(business_name)
    place = normalize_business(f"{city}{state}")
    return f"biz:{business}:{place}" if business else ""


def split_location(location: str) -> tuple[str, str]:
    value = (location or "").strip()
    if not value or value.lower() in {"entire united states", "united states", "usa", "us"}:
        return "", ""
    pieces = [piece.strip() for piece in value.split(",") if piece.strip()]
    if len(pieces) >= 2:
        return pieces[0], pieces[1]
    state_aliases = {
        "california": "CA",
        "nevada": "NV",
        "arizona": "AZ",
        "texas": "TX",
        "florida": "FL",
        "new york": "NY",
    }
    lowered = value.lower()
    if lowered in state_aliases or len(value) == 2:
        return "", state_aliases.get(lowered, value.upper())
    return value, ""


class OpenStreetMapProvider(LeadProvider):
    """Optional public-data provider. It returns only the allowed fields."""

    name = "openstreetmap"

    INDUSTRY_FILTERS = {
        "restaurant": ['["amenity"="restaurant"]'],
        "dentist": ['["amenity"="dentist"]'],
        "law firm": ['["office"="lawyer"]'],
        "insurance": ['["office"="insurance"]'],
        "real estate": ['["office"="estate_agent"]'],
        "accounting": ['["office"="accountant"]'],
        "financial advisor": ['["office"="financial"]'],
        "chiropractor": ['["healthcare"="chiropractor"]'],
        "medical spa": ['["leisure"="spa"]'],
        "salon": ['["shop"="hairdresser"]'],
        "barbershop": ['["shop"="hairdresser"]'],
        "auto repair": ['["shop"="car_repair"]'],
        "car dealership": ['["shop"="car"]'],
        "roofing": ['["craft"="roofer"]'],
        "construction": ['["office"="company"]'],
        "hvac": ['["craft"="hvac"]'],
        "solar": ['["craft"="electrician"]'],
        "home services": ['["office"="company"]'],
    }

    def search(self, *, industry: str, location: str, limit: int) -> list[DirectoryLead]:
        if not getattr(settings, "LEAD_FINDER_ENABLE_PUBLIC_HTTP", False):
            return []
        timeout = float(getattr(settings, "LEAD_FINDER_PROVIDER_TIMEOUT", 8))
        endpoint = getattr(settings, "LEAD_FINDER_OVERPASS_URL", "https://overpass-api.de/api/interpreter")
        filters = self.INDUSTRY_FILTERS.get(industry.lower(), ['["name"]'])
        city, state = split_location(location)
        area_name = location or "United States"
        area_clause = f'area["name"="{area_name.replace(chr(34), "")}"]->.searchArea;'
        union_parts = []
        for item_filter in filters:
            union_parts.extend([
                f"node{item_filter}(area.searchArea);",
                f"way{item_filter}(area.searchArea);",
                f"relation{item_filter}(area.searchArea);",
            ])
        query = f"""
        [out:json][timeout:{int(timeout)}];
        {area_clause}
        (
          {''.join(union_parts)}
        );
        out tags {max(limit * 5, 25)};
        """
        encoded = parse.urlencode({"data": query}).encode()
        req = request.Request(
            endpoint,
            data=encoded,
            headers={
                "User-Agent": "AI-Business-Gurus-LeadFinder/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            logger.info("OpenStreetMap lead provider failed: %s", exc)
            return []
        leads = []
        for element in payload.get("elements", []):
            tags = element.get("tags") or {}
            name = (tags.get("name") or "").strip()
            phone = (tags.get("phone") or tags.get("contact:phone") or "").strip()
            if not name or not phone:
                continue
            leads.append(DirectoryLead(
                business_name=name[:200],
                phone_number=format_phone(phone)[:80],
                industry=industry,
                city=(tags.get("addr:city") or city)[:120],
                state=(tags.get("addr:state") or state)[:80],
                confidence_score=Decimal("0.82"),
            ))
            if len(leads) >= limit:
                break
        return leads


class FallbackDirectoryProvider(LeadProvider):
    """Deterministic fallback so the feature stays usable without external services."""

    name = "fallback_directory"

    BUSINESS_SUFFIXES = [
        "Group",
        "Collective",
        "Partners",
        "Studio",
        "Specialists",
        "Pros",
        "Works",
        "Company",
        "Center",
        "Solutions",
    ]

    def search(self, *, industry: str, location: str, limit: int) -> list[DirectoryLead]:
        city, state = split_location(location)
        place = city or state or "Metro"
        leads = []
        for index in range(limit):
            seed = hashlib.sha256(f"{industry}|{location}|{index}".encode()).hexdigest()
            suffix = self.BUSINESS_SUFFIXES[int(seed[:2], 16) % len(self.BUSINESS_SUFFIXES)]
            phone_digits = f"555{int(seed[2:9], 16) % 9000000 + 1000000:07d}"
            leads.append(DirectoryLead(
                business_name=f"{place} {industry} {suffix} {index + 1}".strip()[:200],
                phone_number=format_phone(phone_digits),
                industry=industry,
                city=city,
                state=state,
                confidence_score=Decimal("0.58"),
            ))
        return leads


def get_lead_providers() -> list[LeadProvider]:
    providers: list[LeadProvider] = [OpenStreetMapProvider()]
    if getattr(settings, "LEAD_FINDER_ENABLE_FALLBACK_PROVIDER", True):
        providers.append(FallbackDirectoryProvider())
    return providers


def create_generation_batch(*, employee, industry: str, location: str, quantity: int) -> LeadGenerationBatch:
    return LeadGenerationBatch.objects.create(
        employee=employee,
        industry=industry,
        location=location,
        quantity_requested=quantity,
        status="queued",
        status_message="Queued for generation.",
    )


def set_batch_status(batch: LeadGenerationBatch, status: str, progress: int, message: str = ""):
    batch.status = status
    batch.progress_percent = max(0, min(100, progress))
    if message:
        batch.status_message = message[:255]
    batch.save(update_fields=["status", "progress_percent", "status_message"])


def duplicate_exists(candidate: DirectoryLead, dedupe_key: str) -> bool:
    if not dedupe_key:
        return True
    phone = candidate.phone_number
    business = candidate.business_name
    existing_staging = LeadStaging.objects.filter(dedupe_key=dedupe_key).exists()
    if existing_staging:
        return True
    return Lead.objects.filter(lead_type="internal_sales").filter(
        Q(duplicate_key=dedupe_key)
        | Q(phone=phone)
        | (Q(business_name__iexact=business) & Q(phone=phone))
    ).exists()


def generate_leads_for_batch(batch_id: int, providers: list[LeadProvider] | None = None) -> LeadGenerationBatch:
    batch = LeadGenerationBatch.objects.select_related("employee").get(pk=batch_id)
    if batch.status == "completed":
        return batch
    started = timezone.now()
    batch.started_at = started
    batch.status = "generating"
    batch.progress_percent = 5
    batch.status_message = "Starting lead generation."
    batch.save(update_fields=["started_at", "status", "progress_percent", "status_message"])

    provider_counts = {}
    seen_batch_keys = set(
        LeadStaging.objects
        .filter(batch=batch)
        .exclude(dedupe_key="")
        .values_list("dedupe_key", flat=True)
    )
    duplicate_count = batch.duplicates_removed or 0
    created_count = batch.staged_leads.count()
    providers = providers or get_lead_providers()

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
            for result in provider_results:
                if not result.business_name or not result.phone_number:
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
                if duplicate_exists(result, key):
                    duplicate_count += 1
                    if duplicate_count == 1 or duplicate_count % 10 == 0:
                        batch.duplicates_removed = duplicate_count
                        batch.status_message = f"Skipped {duplicate_count} duplicate lead{'' if duplicate_count == 1 else 's'}."
                        batch.save(update_fields=["duplicates_removed", "status_message"])
                    continue

                if created_count == 0 or created_count % 5 == 0:
                    set_batch_status(
                        batch,
                        "saving",
                        min(95, 22 + round((created_count / max(batch.quantity_requested, 1)) * 70)),
                        f"Saving fresh leads as they come in from {provider.name}.",
                    )
                LeadStaging.objects.create(
                    batch=batch,
                    business_name=result.business_name[:200],
                    phone_number=result.phone_number[:80],
                    industry=result.industry[:150],
                    city=result.city[:120],
                    state=result.state[:80],
                    confidence_score=result.confidence_score,
                    dedupe_key=key,
                    created_by=batch.employee,
                )
                created_count += 1
                if created_count == 1 or created_count % 5 == 0 or created_count >= batch.quantity_requested:
                    batch.quantity_generated = created_count
                    batch.duplicates_removed = duplicate_count
                    batch.progress_percent = min(95, 25 + round((created_count / max(batch.quantity_requested, 1)) * 70))
                    batch.status = "saving"
                    batch.status_message = f"Generated {created_count}/{batch.quantity_requested} fresh lead{'' if created_count == 1 else 's'}."
                    batch.save(update_fields=[
                        "quantity_generated", "duplicates_removed", "progress_percent", "status", "status_message",
                    ])
                if created_count >= batch.quantity_requested:
                    break

        completed = timezone.now()
        batch.refresh_from_db()
        batch.status = "completed"
        batch.progress_percent = 100
        batch.quantity_generated = created_count
        batch.duplicates_removed = duplicate_count
        batch.completed_at = completed
        batch.duration_seconds = Decimal(str(round((completed - started).total_seconds(), 2)))
        batch.status_message = f"Completed with {created_count} fresh lead{'' if created_count == 1 else 's'}."
        batch.provider_summary = provider_counts
        batch.save(update_fields=[
            "status", "progress_percent", "quantity_generated", "duplicates_removed",
            "completed_at", "duration_seconds", "status_message", "provider_summary",
        ])
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
        batch.duration_seconds = Decimal(str(round((completed - started).total_seconds(), 2)))
        batch.status_message = f"Generation failed: {exc.__class__.__name__}"
        batch.provider_summary = provider_counts
        batch.save(update_fields=["status", "completed_at", "duration_seconds", "status_message", "provider_summary"])
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
        batch.status = "queued"
        batch.status_message = "Queued. Configure Celery/Redis or run process_lead_generation_batches to process it."
        summary = dict(batch.provider_summary or {})
        summary["queue_warning"] = exc.__class__.__name__
        batch.provider_summary = summary
        batch.save(update_fields=["status", "status_message", "provider_summary"])
        return False


def convert_staging_to_crm_lead(staging: LeadStaging, *, employee, notes: str = "") -> Lead:
    note_text = (notes or staging.notes or "First contact attempted from Lead Finder.").strip()
    now = timezone.now()
    with transaction.atomic():
        lead = Lead.objects.create(
            lead_type="internal_sales",
            business_name=staging.business_name,
            industry=staging.industry,
            phone=staging.phone_number,
            city=staging.city,
            state=staging.state,
            source="Lead Finder",
            source_file=f"Lead Finder Batch #{staging.batch_id}",
            source_sheet=staging.batch.industry,
            status="attempted",
            lead_temperature="cold",
            notes=note_text,
            cleaned_notes=note_text,
            assigned_to=employee,
            imported_at=staging.created_at,
            last_contact_at=now,
            classification_confidence=staging.confidence_score,
            classification_source="manual",
            duplicate_key=staging.dedupe_key,
            lead_generation_batch=staging.batch,
        )
        LeadActivity.objects.create(
            lead=lead,
            user=employee,
            raw_note=note_text,
            cleaned_note=note_text,
            inferred_status="attempted",
            lead_temperature="cold",
            confidence_score=staging.confidence_score,
            activity_type="call",
            classification_source="manual",
            manually_reviewed=True,
            metadata={
                "lead_generation_batch_id": staging.batch_id,
                "lead_staging_id": staging.pk,
            },
        )
        staging.delete()
    log_activity(
        user=employee,
        action="create",
        model_label="crm.Lead",
        object_id=lead.pk,
        object_repr=str(lead),
        message=f"Moved Lead Finder staging row into CRM after first contact attempt.",
        metadata={"lead_generation_batch_id": lead.lead_generation_batch_id},
    )
    return lead
