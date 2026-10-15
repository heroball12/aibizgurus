"""Server-owned ZoomInfo previews; confirmation never trusts posted lead fields."""
import csv
import io
from datetime import timedelta

from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from audit.utils import log_activity
from .importers import import_lead_file, parse_lead_file
from .intelligence import csv_safe
from .models import LeadImport, LeadUploadPreview
from .views import employee_required, is_sales_manager
from .zoominfo_import import find_match, identity, normalized, value


def prepare_preview(request, uploaded, parsed, *, selected_sheet="", assigned_to=None):
    LeadUploadPreview.objects.filter(created_at__lt=timezone.now() - timedelta(minutes=30)).delete()
    uploaded.seek(0)
    draft = LeadUploadPreview.objects.create(
        uploaded_by=request.user, original_filename=uploaded.name[:255], content=uploaded.read(),
        selected_sheet=selected_sheet, assigned_to=assigned_to,
    )
    return redirect("lead_import_preview", pk=draft.pk)


@employee_required
@never_cache
@require_GET
def preview(request, pk):
    draft = get_object_or_404(LeadUploadPreview, pk=pk, uploaded_by=request.user)
    if draft.confirmed_import_id:
        return redirect("lead_import_detail", pk=draft.confirmed_import_id)
    if draft.created_at < timezone.now() - timedelta(minutes=30):
        messages.error(request, "This preview expired. Upload the file again.")
        return redirect("lead_upload")
    uploaded = SimpleUploadedFile(draft.original_filename, bytes(draft.content))
    parsed = parse_lead_file(uploaded, selected_sheet=draft.selected_sheet, default_assigned_to=draft.assigned_to,
                             force_assigned_to=None if is_sales_manager(request.user) else request.user)
    if parsed.errors:
        messages.error(request, " ".join(parsed.errors[:3]))
        return redirect("lead_upload")
    records, seen, companies = [], set(), set()
    counts = {"new": 0, "matched": 0, "protected": 0, "repeated": 0}
    for row in parsed.rows:
        if row.source_format != "zoominfo":
            records.append({"data": row.data, "outcome": "Tracker row", "row": row.row_number})
            continue
        token = identity(row.raw)
        company = value(normalized(row.raw), "ZoomInfo Company ID", "Company Name")
        if company:
            companies.add(company)
        existing = find_match(row)
        if existing and not is_sales_manager(request.user) and existing.assigned_to_id not in (None, request.user.pk):
            outcome = "Already assigned · skipped"
            counts["protected"] += 1
        elif token in seen:
            outcome = "Repeated contact · merge source details"
            counts["repeated"] += 1
        elif existing:
            outcome = "Match · preserve CRM progress"
            counts["matched"] += 1
        else:
            outcome = "New person"
            counts["new"] += 1
        seen.add(token)
        records.append({"data": row.data, "outcome": outcome, "row": row.row_number})
    response = render(request, "crm/import_preview.html", {
        "draft": draft, "records": records[:50], "total": len(parsed.rows),
        "counts": counts, "company_count": len(companies), "column_count": len(parsed.source_headers),
        "headers": parsed.source_headers, "more_rows": max(0, len(records) - 50),
        "context_sheet_url": "",
    })
    response["Cache-Control"] = "private, no-store"
    return response


@employee_required
@never_cache
@require_POST
def confirm_import(request, pk):
    # The row lock makes double-click/retry confirmation idempotent.
    with transaction.atomic():
        draft = get_object_or_404(LeadUploadPreview.objects.select_for_update(), pk=pk, uploaded_by=request.user)
        if draft.confirmed_import_id:
            return redirect("lead_import_detail", pk=draft.confirmed_import_id)
        if draft.created_at < timezone.now() - timedelta(minutes=30):
            messages.error(request, "This upload preview expired. Upload the file again to review fresh matches.")
            return redirect("lead_upload")
        assignee = draft.assigned_to
        if assignee and not assignee.is_active:
            messages.error(request, "The selected employee is no longer active. Upload again and choose an active employee.")
            return redirect("lead_upload")
        forced = None if is_sales_manager(request.user) else request.user
        upload = SimpleUploadedFile(draft.original_filename, bytes(draft.content))
        try:
            with transaction.atomic():
                lead_import, parsed = import_lead_file(
                    upload, uploaded_by=request.user, selected_sheet=draft.selected_sheet,
                    default_assigned_to=assignee, force_assigned_to=forced,
                    protect_existing_assignees_for=forced,
                )
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Confirmed lead upload failed")
            messages.error(request, "The import could not finish. No changes were saved. Return to the preview and try again.")
            return redirect("lead_import_preview", pk=draft.pk)
        if parsed.errors:
            messages.error(request, "Import stopped. " + " ".join(parsed.errors[:3]))
            return redirect("lead_upload")
        draft.confirmed_import = lead_import
        draft.content = b""
        draft.save(update_fields=["confirmed_import", "content"])
        log_activity(user=request.user, request=request, action="create", model_label="crm.LeadImport",
                     object_id=lead_import.pk, object_repr=str(lead_import), message="Imported ZoomInfo company and contact records.",
                     metadata={"created": lead_import.imported_count, "updated": lead_import.updated_count})
    people_label = "person" if lead_import.imported_count == 1 else "people"
    messages.success(request, f"Import complete: {lead_import.imported_count} {people_label} created, {lead_import.updated_count} matched. Company profiles and all exported columns are saved.")
    return redirect("lead_import_detail", pk=lead_import.pk)


@employee_required
@never_cache
@require_GET
def source_export(request, pk):
    imports = LeadImport.objects.all()
    if not is_sales_manager(request.user):
        imports = imports.filter(uploaded_by=request.user)
    lead_import = get_object_or_404(imports, pk=pk)
    activities = lead_import.activities.filter(metadata__source_format="zoominfo").select_related("lead").order_by("pk")
    if not is_sales_manager(request.user):
        activities = activities.filter(lead__assigned_to=request.user, lead__archived=False)
    headers = lead_import.import_summary.get("source_headers", [])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([csv_safe(h) for h in headers])
    for item in activities:
        raw = item.metadata.get("source_data", {})
        writer.writerow([csv_safe(str(raw.get(h) or "")) for h in headers])
    response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="zoominfo-import-{lead_import.pk}.csv"'
    return response
