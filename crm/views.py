import csv
import logging

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils import timezone

from audit.utils import log_activity
from .forms import LeadCSVUploadForm, LeadForm, LeadIntelligenceForm, LeadNoteForm
from .importers import import_lead_file, parse_csv_file
from .intelligence import csv_safe, draft_follow_up_email
from .models import ClassificationCorrection, Lead, LeadActivity, LeadImport


User = get_user_model()
logger = logging.getLogger(__name__)


def paginate(request, queryset, per_page=50):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def parse_internal_lead_csv(uploaded_file):
    """Backward-compatible parser used by older tests and admin scripts."""
    parsed = parse_csv_file(uploaded_file)
    return [row.data for row in parsed.rows], parsed.errors


def is_sales_manager(user):
    return user.is_superuser or getattr(user, "role", "") in {"admin", "owner"}


def can_delete_internal_leads(user):
    return user.is_superuser or getattr(user, "role", "") in {"admin", "owner"}


def internal_leads_for_user(user):
    qs = Lead.objects.filter(lead_type="internal_sales", archived=False)
    if is_sales_manager(user):
        return qs
    return qs.filter(assigned_to=user)


def get_internal_lead_or_404(user, pk):
    return get_object_or_404(internal_leads_for_user(user), pk=pk)


LEAD_SORTS = {
    "newest": "-created_at",
    "oldest": "created_at",
    "assigned": "assigned_to__first_name",
    "sheet": "source_sheet",
    "file": "source_file",
    "status": "status",
    "temperature": "-lead_temperature",
    "followup": "follow_up_date",
    "business": "business_name",
}


def assignable_staff():
    return User.objects.filter(role__in=["employee", "admin"], is_active=True).order_by("first_name", "username")


def lead_filter_values(request):
    return {
        "q": request.GET.get("q", "").strip(),
        "assigned_to": request.GET.get("assigned_to", "").strip(),
        "source_file": request.GET.get("source_file", "").strip(),
        "source_sheet": request.GET.get("source_sheet", "").strip(),
        "status": request.GET.get("status", "").strip(),
        "temperature": request.GET.get("temperature", "").strip(),
        "sort": request.GET.get("sort", "newest").strip() or "newest",
    }


def lead_filter_values_from_post(request):
    return {
        "q": request.POST.get("filter_q", "").strip(),
        "assigned_to": request.POST.get("filter_assigned_to", "").strip(),
        "source_file": request.POST.get("filter_source_file", "").strip(),
        "source_sheet": request.POST.get("filter_source_sheet", "").strip(),
        "status": request.POST.get("filter_status", "").strip(),
        "temperature": request.POST.get("filter_temperature", "").strip(),
        "sort": request.POST.get("filter_sort", "newest").strip() or "newest",
    }


def apply_lead_filters(leads, filters):
    if filters["q"]:
        q = filters["q"]
        leads = leads.filter(
            Q(name__icontains=q)
            | Q(business_name__icontains=q)
            | Q(phone__icontains=q)
            | Q(email__icontains=q)
            | Q(website__icontains=q)
            | Q(notes__icontains=q)
            | Q(cleaned_notes__icontains=q)
        )
    if filters["assigned_to"]:
        if filters["assigned_to"] == "unassigned":
            leads = leads.filter(assigned_to__isnull=True)
        else:
            leads = leads.filter(assigned_to_id=filters["assigned_to"])
    if filters["source_file"]:
        leads = leads.filter(source_file=filters["source_file"])
    if filters["source_sheet"]:
        leads = leads.filter(source_sheet=filters["source_sheet"])
    if filters["status"]:
        leads = leads.filter(status=filters["status"])
    if filters["temperature"]:
        leads = leads.filter(lead_temperature=filters["temperature"])
    return leads


def order_leads(leads, sort_key):
    primary = LEAD_SORTS.get(sort_key, "-created_at")
    ordering = [primary]
    if primary not in {"-created_at", "created_at"}:
        ordering.append("-created_at")
    return leads.order_by(*ordering)


def lead_filter_context(request, base_leads):
    filters = lead_filter_values(request)
    active = base_leads
    return {
        "lead_filters": filters,
        "assignable_users": assignable_staff(),
        "source_files": active.exclude(source_file="").values_list("source_file", flat=True).distinct().order_by("source_file")[:250],
        "source_sheets": active.exclude(source_sheet="").values_list("source_sheet", flat=True).distinct().order_by("source_sheet")[:250],
        "status_choices": Lead.STATUS_CHOICES,
        "temperature_choices": Lead._meta.get_field("lead_temperature").choices,
        "sort_choices": [
            ("newest", "Newest first"),
            ("oldest", "Oldest first"),
            ("assigned", "Assigned person"),
            ("sheet", "Sheet name"),
            ("file", "Source file"),
            ("status", "Status"),
            ("temperature", "Temperature"),
            ("followup", "Follow-up date"),
            ("business", "Business name"),
        ],
        "query_string": query_without_page(request),
        "can_manage_leads": is_sales_manager(request.user),
    }


def query_without_page(request):
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return query_params.urlencode()


def safe_next_url(request):
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "crm_home"
    if isinstance(next_url, str) and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "crm_home"


def hard_delete_leads(user, request, leads, reason):
    lead_ids = list(leads.values_list("pk", flat=True))
    count = len(lead_ids)
    if not count:
        return 0
    sample = list(leads.values_list("business_name", "name")[:10])
    deleted, _ = leads.delete()
    log_activity(
        user=user,
        request=request,
        action="delete",
        model_label="crm.Lead",
        message=f"Hard-deleted {count} internal sales lead{'' if count == 1 else 's'} ({reason}).",
        metadata={
            "lead_ids": lead_ids[:200],
            "sample": [business or name for business, name in sample],
            "requested_count": count,
            "deleted_objects": deleted,
            "reason": reason,
        },
    )
    return count


def update_leads_from_action(user, request, leads):
    updates = {}
    status = request.POST.get("status", "").strip()
    temperature = request.POST.get("lead_temperature", "").strip()
    follow_up_date = request.POST.get("follow_up_date", "").strip()
    assigned_to = request.POST.get("assigned_to", "").strip()
    needs_review = request.POST.get("needs_review", "")

    valid_statuses = {value for value, _ in Lead.STATUS_CHOICES}
    valid_temperatures = {value for value, _ in Lead._meta.get_field("lead_temperature").choices}
    if status in valid_statuses:
        updates["status"] = status
    if temperature in valid_temperatures:
        updates["lead_temperature"] = temperature
    if follow_up_date:
        parsed_date = parse_date(follow_up_date)
        if parsed_date:
            updates["follow_up_date"] = parsed_date
    if assigned_to and is_sales_manager(user):
        if assigned_to == "unassigned":
            updates["assigned_to_id"] = None
        elif User.objects.filter(pk=assigned_to, role__in=["employee", "admin"], is_active=True).exists():
            updates["assigned_to_id"] = assigned_to
    if needs_review in {"on", "true", "1", "yes"}:
        updates["needs_review"] = True
    elif needs_review in {"off", "false", "0", "no"}:
        updates["needs_review"] = False

    if not updates:
        return 0
    count = leads.update(**updates)
    log_activity(
        user=user,
        request=request,
        action="update",
        model_label="crm.Lead",
        message=f"Bulk-updated {count} internal sales lead{'' if count == 1 else 's'}.",
        metadata={"updates": updates, "count": count},
    )
    return count


def sales_metrics(qs):
    today = timezone.localdate()
    closed_statuses = ["closed_won", "closed_lost", "not_interested", "do_not_contact", "permanently_closed"]
    data = qs.aggregate(
        total=Count("id"),
        worked=Count("id", filter=~Q(notes="")),
        unique_businesses=Count("business_name", filter=~Q(business_name=""), distinct=True),
        warm=Count("id", filter=Q(lead_temperature="warm")),
        hot=Count("id", filter=Q(lead_temperature="hot")),
        followups_due=Count(
            "id",
            filter=(Q(follow_up_date__lte=today) | Q(status__in=["callback_requested", "follow_up"])) & ~Q(status__in=closed_statuses),
        ),
        needs_review=Count("id", filter=Q(needs_review=True)),
        emails_requested=Count("id", filter=Q(status="email_requested")),
        callbacks_requested=Count("id", filter=Q(status="callback_requested")),
        appointments=Count("id", filter=Q(status__in=["appointment_scheduled", "appointment_completed"])),
        closed_won=Count("id", filter=Q(status="closed_won")),
        closed_lost=Count("id", filter=Q(status="closed_lost")),
    )
    total = data["total"] or 0
    worked = data["worked"] or 0
    return {
        "total": total,
        "worked": worked,
        "unique_businesses": data["unique_businesses"] or 0,
        "warm": data["warm"] or 0,
        "hot": data["hot"] or 0,
        "followups_due": data["followups_due"] or 0,
        "needs_review": data["needs_review"] or 0,
        "emails_requested": data["emails_requested"] or 0,
        "callbacks_requested": data["callbacks_requested"] or 0,
        "appointments": data["appointments"] or 0,
        "closed_won": data["closed_won"] or 0,
        "closed_lost": data["closed_lost"] or 0,
        "contact_rate": round((worked / total) * 100) if total else 0,
    }


def build_scorecards(leads, limit=None):
    today = timezone.localdate()
    rows = list(
        leads.exclude(assigned_to__isnull=True)
        .values("assigned_to")
        .annotate(
            total=Count("id"),
            worked=Count("id", filter=~Q(notes="")),
            warm=Count("id", filter=Q(lead_temperature="warm")),
            hot=Count("id", filter=Q(lead_temperature="hot")),
            warm_hot=Count("id", filter=Q(lead_temperature__in=["warm", "hot"])),
            emails=Count("id", filter=Q(status="email_requested")),
            callbacks=Count("id", filter=Q(status="callback_requested")),
            appointments=Count("id", filter=Q(status__in=["appointment_scheduled", "appointment_completed"])),
            followups=Count("id", filter=Q(follow_up_date__lte=today)),
            overdue=Count("id", filter=Q(follow_up_date__lt=today)),
        )
        .order_by("-warm_hot", "-total")
    )
    if limit:
        rows = rows[:limit]
    users = User.objects.in_bulk([row["assigned_to"] for row in rows])
    cards = []
    for row in rows:
        total = row["total"] or 0
        worked = row["worked"] or 0
        cards.append({
            "user": users.get(row["assigned_to"]),
            "total": total,
            "worked": worked,
            "contact_rate": round((worked / total) * 100) if total else 0,
            "warm": row["warm"],
            "hot": row["hot"],
            "warm_hot": row["warm_hot"],
            "emails": row["emails"],
            "callbacks": row["callbacks"],
            "appointments": row["appointments"],
            "followups": row["followups"],
            "overdue": row["overdue"],
        })
    return cards

def employee_required(view):
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_employee_or_admin():
            messages.error(request, "Employee access required.")
            return redirect("portal_home")
        return view(request, *args, **kwargs)
    return wrapper

@employee_required
def crm_home(request):
    leads = internal_leads_for_user(request.user).select_related("assigned_to")
    today = timezone.localdate()
    imports = LeadImport.objects.select_related("uploaded_by")
    if not is_sales_manager(request.user):
        imports = imports.filter(uploaded_by=request.user)
    imports = imports.order_by("-created_at")[:6]
    scorecards = build_scorecards(leads, limit=8)
    filters = lead_filter_values(request)
    filtered_leads = order_leads(apply_lead_filters(leads, filters), filters["sort"])
    context = {
        "leads": filtered_leads[:25],
        "page_obj": paginate(request, filtered_leads, 100),
        "filtered_count": filtered_leads.count(),
        "metrics": sales_metrics(leads),
        "warm_leads": leads.filter(lead_temperature__in=["warm", "hot"]).order_by("-lead_temperature", "follow_up_date", "-created_at")[:10],
        "followups": leads.filter(Q(follow_up_date__lte=today) | Q(status__in=["callback_requested", "follow_up", "email_requested"])).order_by("follow_up_date", "-created_at")[:10],
        "review_leads": leads.filter(needs_review=True).order_by("-created_at")[:10],
        "imports": imports,
        "scorecards": scorecards,
        "is_sales_manager": is_sales_manager(request.user),
        **lead_filter_context(request, leads),
    }
    return render(request, "crm/crm_home.html", context)

@employee_required
def lead_create(request):
    if request.method == "POST":
        form = LeadForm(request.POST, user=request.user, is_sales_manager=is_sales_manager(request.user))
        if form.is_valid():
            lead = form.save(commit=False)
            lead.lead_type = "internal_sales"
            lead.client = None
            lead.ai_instance = None
            if not is_sales_manager(request.user):
                lead.assigned_to = request.user
            if lead.notes and not lead.cleaned_notes:
                from .intelligence import classify_sales_note, duplicate_fingerprint

                classification = classify_sales_note(lead.notes, imported_status=lead.status)
                lead.status = classification.status
                lead.lead_temperature = classification.temperature
                lead.cleaned_notes = classification.cleaned_note
                lead.classification_confidence = classification.confidence
                lead.classification_source = "rule"
                lead.needs_review = classification.needs_review
                lead.duplicate_key = duplicate_fingerprint(
                    business_name=lead.business_name,
                    phone=lead.phone,
                    website=lead.website,
                    email=lead.email,
                    address=lead.address,
                )
            lead.save()
            if lead.notes:
                LeadActivity.objects.create(
                    lead=lead,
                    user=request.user,
                    raw_note=lead.notes,
                    cleaned_note=lead.cleaned_notes,
                    inferred_status=lead.status,
                    lead_temperature=lead.lead_temperature,
                    confidence_score=lead.classification_confidence,
                    activity_type="manual_note",
                    classification_source=lead.classification_source,
                )
            log_activity(user=request.user, request=request, action="create", model_label="crm.Lead", object_id=lead.pk, object_repr=str(lead), message="Created internal sales lead.")
            messages.success(request, "Lead created.")
            return redirect("crm_home")
    else:
        form = LeadForm(user=request.user, is_sales_manager=is_sales_manager(request.user))
    return render(request, "crm/lead_form.html", {"form": form})


@employee_required
def lead_upload(request):
    import_errors = []
    lead_import = None
    if request.method == "POST":
        form = LeadCSVUploadForm(request.POST, request.FILES, user=request.user, is_sales_manager=is_sales_manager(request.user))
        if form.is_valid():
            forced_assignee = None if is_sales_manager(request.user) else request.user
            try:
                lead_import, parsed = import_lead_file(
                    form.cleaned_data["csv_file"],
                    uploaded_by=request.user,
                    selected_sheet=form.cleaned_data.get("sheet_name", ""),
                    default_assigned_to=form.cleaned_data.get("default_assigned_to"),
                    force_assigned_to=forced_assignee,
                    protect_existing_assignees_for=forced_assignee,
                )
            except Exception as exc:
                logger.exception("Lead import failed for %s", getattr(form.cleaned_data["csv_file"], "name", "uploaded file"))
                lead_import = None
                parsed = None
                import_errors = [
                    "The tracker could not be imported. No leads were saved.",
                    "If this happened right after a deploy, run migrations on Render and try again.",
                    f"Technical detail: {exc.__class__.__name__}",
                ]
            else:
                import_errors = parsed.errors
            if lead_import:
                log_activity(
                    user=request.user,
                    request=request,
                    action="create",
                    model_label="crm.LeadImport",
                    object_id=lead_import.pk,
                    object_repr=str(lead_import),
                    message=f"Imported {lead_import.imported_count} sales intelligence leads.",
                    metadata={"filename": lead_import.original_filename, "rows": lead_import.imported_count},
                )
                messages.success(request, f"Import complete: {lead_import.imported_count} created, {lead_import.updated_count} updated. Review the report below.")
                return redirect("lead_import_detail", pk=lead_import.pk)
    else:
        form = LeadCSVUploadForm(user=request.user, is_sales_manager=is_sales_manager(request.user))
    return render(request, "crm/lead_upload.html", {
        "form": form,
        "import_errors": import_errors[:25],
        "lead_import": lead_import,
        "sample_headers": "name,business_name,industry,phone,email,website,address,city,state,poc,source,status,notes,value,follow_up_date,assigned_to",
    })

@employee_required
def lead_detail(request, pk):
    lead = get_internal_lead_or_404(request.user, pk)
    if request.method == "POST":
        action = request.POST.get("action", "add_note")
        if action == "save_intelligence":
            original = {
                "status": lead.status,
                "temperature": lead.lead_temperature,
                "cleaned": lead.cleaned_notes,
            }
            intelligence_form = LeadIntelligenceForm(
                request.POST,
                instance=lead,
                user=request.user,
                is_sales_manager=is_sales_manager(request.user),
            )
            note_form = LeadNoteForm()
            if intelligence_form.is_valid():
                updated = intelligence_form.save(commit=False)
                updated.classification_source = "manual"
                if not is_sales_manager(request.user):
                    updated.assigned_to = request.user
                updated.save()
                ClassificationCorrection.objects.create(
                    lead=lead,
                    original_status=original["status"],
                    corrected_status=updated.status,
                    original_temperature=original["temperature"],
                    corrected_temperature=updated.lead_temperature,
                    original_cleaned_note=original["cleaned"],
                    corrected_cleaned_note=updated.cleaned_notes,
                    corrected_by=request.user,
                    reason=intelligence_form.cleaned_data.get("correction_reason", ""),
                )
                log_activity(user=request.user, request=request, action="update", model_label="crm.Lead", object_id=lead.pk, object_repr=str(lead), message="Updated sales intelligence classification.")
                messages.success(request, "Classification updated.")
                return redirect("lead_detail", pk=lead.pk)
        else:
            form = LeadNoteForm(request.POST)
            if form.is_valid():
                note = form.save(commit=False)
                note.lead = lead
                note.user = request.user
                note.save()
                LeadActivity.objects.create(
                    lead=lead,
                    user=request.user,
                    raw_note=note.note,
                    cleaned_note=note.note,
                    inferred_status=lead.status,
                    lead_temperature=lead.lead_temperature,
                    activity_type="manual_note",
                    classification_source="manual",
                    manually_reviewed=True,
                )
                messages.success(request, "Note added.")
                return redirect("lead_detail", pk=lead.pk)
            note_form = form
            intelligence_form = LeadIntelligenceForm(instance=lead, user=request.user, is_sales_manager=is_sales_manager(request.user))
    else:
        note_form = LeadNoteForm()
        intelligence_form = LeadIntelligenceForm(instance=lead, user=request.user, is_sales_manager=is_sales_manager(request.user))
    if request.method == "POST" and request.POST.get("action") == "save_intelligence":
        pass
    else:
        note_form = locals().get("note_form", LeadNoteForm())
        intelligence_form = locals().get(
            "intelligence_form",
            LeadIntelligenceForm(instance=lead, user=request.user, is_sales_manager=is_sales_manager(request.user)),
        )
    return render(request, "crm/lead_detail.html", {
        "lead": lead,
        "note_form": note_form,
        "intelligence_form": intelligence_form,
        "activities": lead.activities.select_related("user", "original_import")[:25],
        "email_draft": draft_follow_up_email(lead) if request.GET.get("draft") == "email" else "",
        "can_delete_lead": can_delete_internal_leads(request.user),
    })

@employee_required
def lead_import_detail(request, pk):
    imports = LeadImport.objects.select_related("uploaded_by")
    if not is_sales_manager(request.user):
        imports = imports.filter(uploaded_by=request.user)
    lead_import = get_object_or_404(imports, pk=pk)
    lead_ids = lead_import.activities.values_list("lead_id", flat=True)
    base_leads = internal_leads_for_user(request.user).filter(pk__in=lead_ids).select_related("assigned_to")
    filters = lead_filter_values(request)
    leads = order_leads(apply_lead_filters(base_leads, filters), filters["sort"])
    sheet_groups = list(
        internal_leads_for_user(request.user)
        .filter(pk__in=lead_ids)
        .values("source_sheet")
        .annotate(
            total_count=Count("id"),
            review_count=Count("id", filter=Q(needs_review=True)),
            warm_hot_count=Count("id", filter=Q(lead_temperature__in=["warm", "hot"])),
        )
        .order_by("source_sheet")
    )
    return render(request, "crm/import_detail.html", {
        "lead_import": lead_import,
        "page_obj": paginate(request, leads, 75),
        "sheet_groups": sheet_groups,
        "can_delete_import_sheets": is_sales_manager(request.user),
        "filtered_count": leads.count(),
        **lead_filter_context(request, base_leads),
    })


@employee_required
def lead_import_delete_sheet(request, pk):
    imports = LeadImport.objects.select_related("uploaded_by")
    if not is_sales_manager(request.user):
        imports = imports.filter(uploaded_by=request.user)
    lead_import = get_object_or_404(imports, pk=pk)
    if not is_sales_manager(request.user):
        messages.error(request, "Only owner/admin users can delete leads by sheet.")
        return redirect("lead_import_detail", pk=lead_import.pk)
    if request.method != "POST":
        messages.error(request, "Use the sheet action button on the import report.")
        return redirect("lead_import_detail", pk=lead_import.pk)

    source_sheet = (request.POST.get("source_sheet") or "CSV").strip() or "CSV"
    lead_ids = (
        lead_import.activities
        .filter(lead__source_sheet=source_sheet, lead__lead_type="internal_sales")
        .values_list("lead_id", flat=True)
        .distinct()
    )
    leads = Lead.objects.filter(pk__in=lead_ids, lead_type="internal_sales", archived=False)
    count = hard_delete_leads(request.user, request, leads, f"import sheet {lead_import.original_filename}/{source_sheet}")
    messages.success(request, f"Permanently deleted {count} lead{'' if count == 1 else 's'} from sheet '{source_sheet}'.")
    return redirect("lead_import_detail", pk=lead_import.pk)


@employee_required
def lead_queue(request, queue_type):
    leads = internal_leads_for_user(request.user).select_related("assigned_to")
    today = timezone.localdate()
    titles = {
        "warm": "Warm + Hot Leads",
        "hot": "Hot Lead Queue",
        "followups": "Follow-Up Queue",
        "review": "Manual Review Queue",
    }
    if queue_type == "warm":
        leads = leads.filter(lead_temperature__in=["warm", "hot"])
    elif queue_type == "hot":
        leads = leads.filter(lead_temperature="hot")
    elif queue_type == "followups":
        leads = leads.filter(Q(follow_up_date__lte=today) | Q(status__in=["callback_requested", "follow_up", "email_requested", "information_requested"]))
    elif queue_type == "review":
        leads = leads.filter(needs_review=True)
    else:
        messages.error(request, "Unknown queue.")
        return redirect("crm_home")
    filters = lead_filter_values(request)
    filtered_leads = order_leads(apply_lead_filters(leads, filters), filters["sort"])
    return render(request, "crm/lead_queue.html", {
        "queue_type": queue_type,
        "title": titles[queue_type],
        "page_obj": paginate(request, filtered_leads, 75),
        "filtered_count": filtered_leads.count(),
        **lead_filter_context(request, leads),
    })


@employee_required
def lead_bulk_action(request):
    if request.method != "POST":
        return redirect("crm_home")
    next_url = safe_next_url(request)
    action = request.POST.get("action", "").strip()
    selected_ids = request.POST.getlist("lead_ids")
    single_id = request.POST.get("lead_id", "").strip()
    if single_id:
        selected_ids = [single_id]
    leads = internal_leads_for_user(request.user).filter(pk__in=selected_ids, lead_type="internal_sales")

    if action in {"delete", "delete_selected"}:
        if not selected_ids:
            messages.error(request, "Select at least one lead first.")
            return redirect(next_url)
        if not can_delete_internal_leads(request.user):
            messages.error(request, "Only owner/admin users can permanently delete leads.")
            return redirect(next_url)
        count = hard_delete_leads(request.user, request, leads, "bulk/list action")
        messages.success(request, f"Permanently deleted {count} lead{'' if count == 1 else 's'}.")
        return redirect(next_url)

    if action == "delete_filtered":
        if not can_delete_internal_leads(request.user):
            messages.error(request, "Only owner/admin users can permanently delete leads.")
            return redirect(next_url)
        filters = lead_filter_values_from_post(request)
        filtered = apply_lead_filters(internal_leads_for_user(request.user), filters)
        count = hard_delete_leads(request.user, request, filtered, "all matching active filters")
        messages.success(request, f"Permanently deleted {count} matching lead{'' if count == 1 else 's'}.")
        return redirect(next_url)

    if action in {"update", "update_selected"}:
        if not selected_ids:
            messages.error(request, "Select at least one lead first.")
            return redirect(next_url)
        count = update_leads_from_action(request.user, request, leads)
        if count:
            messages.success(request, f"Updated {count} lead{'' if count == 1 else 's'}.")
        else:
            messages.info(request, "No lead changes were selected.")
        return redirect(next_url)

    messages.error(request, "Unknown lead action.")
    return redirect(next_url)


@employee_required
def scorecards(request):
    leads = internal_leads_for_user(request.user)
    return render(request, "crm/scorecards.html", {"scorecards": build_scorecards(leads)})


@employee_required
def export_leads(request):
    leads = internal_leads_for_user(request.user).select_related("assigned_to")
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="sales-intelligence-leads.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "business_name", "name", "phone", "email", "website", "industry", "status",
        "temperature", "assigned_to", "follow_up_date", "source_file", "source_sheet",
        "original_notes", "cleaned_notes", "confidence",
    ])
    for lead in leads:
        writer.writerow([
            csv_safe(lead.business_name),
            csv_safe(lead.name),
            csv_safe(lead.phone),
            csv_safe(lead.email),
            csv_safe(lead.website),
            csv_safe(lead.industry),
            lead.get_status_display(),
            lead.get_lead_temperature_display(),
            csv_safe(getattr(lead.assigned_to, "username", "")),
            lead.follow_up_date or "",
            csv_safe(lead.source_file),
            csv_safe(lead.source_sheet),
            csv_safe(lead.notes),
            csv_safe(lead.cleaned_notes),
            lead.classification_confidence,
        ])
    log_activity(user=request.user, request=request, action="export", model_label="crm.Lead", message="Exported sales intelligence leads.")
    return response

@employee_required
def lead_edit(request, pk):
    lead = get_internal_lead_or_404(request.user, pk)
    if request.method == "POST":
        form = LeadForm(request.POST, instance=lead, user=request.user, is_sales_manager=is_sales_manager(request.user))
        if form.is_valid():
            updated = form.save(commit=False)
            updated.lead_type = "internal_sales"
            updated.client = None
            updated.ai_instance = None
            if not is_sales_manager(request.user):
                updated.assigned_to = request.user
            updated.save()
            messages.success(request, "Lead updated.")
            return redirect("lead_detail", pk=lead.pk)
    else:
        form = LeadForm(instance=lead, user=request.user, is_sales_manager=is_sales_manager(request.user))
    return render(request, "crm/lead_form.html", {"form": form, "lead": lead})


@employee_required
def lead_delete(request, pk):
    lead = get_internal_lead_or_404(request.user, pk)
    if not can_delete_internal_leads(request.user):
        messages.error(request, "Only admins and owners can delete internal leads.")
        return redirect("lead_detail", pk=lead.pk)
    if request.method != "POST":
        messages.error(request, "Use the delete button on the lead page to remove a lead.")
        return redirect("lead_detail", pk=lead.pk)

    hard_delete_leads(request.user, request, Lead.objects.filter(pk=lead.pk), "single lead detail action")
    messages.success(request, "Lead permanently deleted from the system.")
    return redirect("crm_home")
