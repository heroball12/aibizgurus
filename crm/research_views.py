from django.http import JsonResponse
from django.db import transaction
from django.utils import timezone
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from core.permissions import employee_required
from core.rate_limits import consume_budget
from .public_site import SiteError
from .views import get_staging_or_404, get_internal_lead_or_404
from .website_research import research_website
from .business_status import verify_business, merge_verification
from .models import LeadActivity


@employee_required
@never_cache
@require_http_methods(["GET", "POST"])
def research(request, pk, pipeline=False):
    getter = get_internal_lead_or_404 if pipeline else get_staging_or_404
    lead = getter(request.user, pk)
    website = lead.website
    saved = lead.website_review if isinstance(lead.website_review, dict) else {}
    report = saved if saved.get("website") == website else {}
    if request.method == "GET":
        if not report:
            return JsonResponse({"error": "No saved website research yet."}, status=404)
    elif not report or request.POST.get("refresh") == "1":
        if not consume_budget(
            "website-research", str(request.user.pk), limit=20, window=3600
        ):
            return JsonResponse(
                {
                    "error": "You’ve reached the hourly website research limit. Try again later."
                },
                status=429,
            )
        if not consume_budget(
            "website-research-row", f"{pipeline}:{pk}", limit=1, window=30
        ):
            return JsonResponse(
                {
                    "error": "This website was just scanned or is still being scanned. Wait 30 seconds before trying again."
                },
                status=429,
            )
        try:
            report = research_website(website)
        except SiteError as exc:
            return JsonResponse({"error": str(exc)}, status=422)
        lead = getter(
            request.user, pk
        )  # Re-check permissions after the network request.
        if lead.website != website:
            return JsonResponse(
                {
                    "error": "The website changed while scanning. Refresh this page and try again."
                },
                status=409,
            )
        lead.website_review = report
        if report.get("business_notice"):
            notice = report["business_notice"]
            lead.business_verification = {
                "status": "needs_review",
                "label": "Possible website closure · review needed",
                "checked_at": report["checked_at"],
                "listing_url": getattr(lead, "source_url", "")
                or (lead.business_verification or {}).get("listing_url", ""),
                "evidence": [{"source": notice["source"], "detail": notice["detail"]}],
            }
        lead.save(update_fields=["website_review", "business_verification"])
    return JsonResponse(
        {
            "html": render_to_string("crm/_website_report.html", {"report": report}),
            "checked_at": report.get("checked_at"),
        }
    )


@employee_required
@never_cache
@require_http_methods(["GET", "POST"])
def verify(request, pk, pipeline=False):
    getter = get_internal_lead_or_404 if pipeline else get_staging_or_404
    lead = getter(request.user, pk)
    if request.method == "POST":
        if request.POST.get("action") == "confirm":
            state, note = (
                request.POST.get("status"),
                request.POST.get("note", "").strip(),
            )
            labels = {
                "confirmed_open": "Employee confirmed operating",
                "confirmed_closed": "Employee confirmed closed",
                "temporarily_closed": "Employee confirmed temporarily closed",
            }
            if state not in labels or not 10 <= len(note) <= 1000:
                return JsonResponse(
                    {
                        "error": "Choose a status and explain how you verified it (10–1,000 characters)."
                    },
                    status=400,
                )
            with transaction.atomic():
                lead = getter(request.user, pk)
                result = {
                    "status": state,
                    "label": labels[state],
                    "checked_at": timezone.now().isoformat(),
                    "listing_url": getattr(lead, "source_url", "")
                    or (lead.business_verification or {}).get("listing_url", ""),
                    "confirmed_by": request.user.get_full_name()
                    or request.user.username,
                    "evidence": [{"detail": note, "source": ""}],
                }
                lead.business_verification = result
                lead.save(update_fields=["business_verification"])
                if pipeline:
                    LeadActivity.objects.create(
                        lead=lead,
                        user=request.user,
                        activity_type="manual_note",
                        classification_source="manual",
                        manually_reviewed=True,
                        raw_note=f"{labels[state]}: {note}",
                        inferred_status=lead.status,
                    )
        else:
            if not consume_budget(
                "business-verify", str(request.user.pk), limit=20, window=3600
            ):
                return JsonResponse(
                    {
                        "error": "You’ve reached the hourly verification limit. Try again later."
                    },
                    status=429,
                )
            if not consume_budget(
                "business-verify-row", f"{pipeline}:{pk}", limit=1, window=30
            ):
                return JsonResponse(
                    {
                        "error": "A check just ran or is in progress. Wait 30 seconds before checking again."
                    },
                    status=429,
                )
            original_website = lead.website
            result, report = verify_business(lead)
            lead = getter(request.user, pk)
            if original_website != lead.website:
                return JsonResponse(
                    {
                        "error": "The business details changed. Refresh before checking again."
                    },
                    status=409,
                )
            result = merge_verification(lead.business_verification, result)
            lead.business_verification = result
            if report:
                lead.website_review = report
            lead.save(update_fields=["business_verification", "website_review"])
    else:
        result = lead.business_verification or {}
    return JsonResponse(
        {
            "html": render_to_string(
                "crm/_business_status.html", {"verification": result}
            ),
            "label": result.get("label", "Operating status unverified"),
            "status": result.get("status", "unverified"),
        }
    )
