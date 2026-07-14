import csv

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from audit.utils import log_activity
from .forms import LeadCSVUploadForm, LeadForm, LeadIntelligenceForm, LeadNoteForm
from .importers import import_lead_file, parse_csv_file
from .intelligence import csv_safe, draft_follow_up_email
from .models import ClassificationCorrection, Lead, LeadActivity, LeadImport


User = get_user_model()


def paginate(request, queryset, per_page=50):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def parse_internal_lead_csv(uploaded_file):
    """Backward-compatible parser used by older tests and admin scripts."""
    parsed = parse_csv_file(uploaded_file)
    return [row.data for row in parsed.rows], parsed.errors


def is_sales_manager(user):
    return user.is_superuser or user.is_staff or getattr(user, "role", "") in {"admin", "owner"}


def can_delete_internal_leads(user):
    return user.is_superuser or getattr(user, "role", "") in {"admin", "owner"}


def internal_leads_for_user(user):
    qs = Lead.objects.filter(lead_type="internal_sales", archived=False)
    if is_sales_manager(user):
        return qs
    return qs.filter(Q(assigned_to=user) | Q(assigned_to__isnull=True))


def get_internal_lead_or_404(user, pk):
    return get_object_or_404(internal_leads_for_user(user), pk=pk)


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
    imports = LeadImport.objects.select_related("uploaded_by").order_by("-created_at")[:6]
    scorecards = build_scorecards(leads, limit=8)
    context = {
        "leads": leads.order_by("-created_at")[:25],
        "metrics": sales_metrics(leads),
        "warm_leads": leads.filter(lead_temperature__in=["warm", "hot"]).order_by("-lead_temperature", "follow_up_date", "-created_at")[:10],
        "followups": leads.filter(Q(follow_up_date__lte=today) | Q(status__in=["callback_requested", "follow_up", "email_requested"])).order_by("follow_up_date", "-created_at")[:10],
        "review_leads": leads.filter(needs_review=True).order_by("-created_at")[:10],
        "imports": imports,
        "scorecards": scorecards,
        "is_sales_manager": is_sales_manager(request.user),
    }
    return render(request, "crm/crm_home.html", context)

@employee_required
def lead_create(request):
    if request.method == "POST":
        form = LeadForm(request.POST)
        if form.is_valid():
            lead = form.save(commit=False)
            lead.lead_type = "internal_sales"
            lead.client = None
            lead.ai_instance = None
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
        form = LeadForm()
    return render(request, "crm/lead_form.html", {"form": form})


@employee_required
def lead_upload(request):
    import_errors = []
    lead_import = None
    if request.method == "POST":
        form = LeadCSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            lead_import, parsed = import_lead_file(
                form.cleaned_data["csv_file"],
                uploaded_by=request.user,
                selected_sheet=form.cleaned_data.get("sheet_name", ""),
                default_assigned_to=form.cleaned_data.get("default_assigned_to"),
            )
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
        form = LeadCSVUploadForm()
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
            intelligence_form = LeadIntelligenceForm(request.POST, instance=lead)
            note_form = LeadNoteForm()
            if intelligence_form.is_valid():
                updated = intelligence_form.save(commit=False)
                updated.classification_source = "manual"
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
            intelligence_form = LeadIntelligenceForm(instance=lead)
    else:
        note_form = LeadNoteForm()
        intelligence_form = LeadIntelligenceForm(instance=lead)
    if request.method == "POST" and request.POST.get("action") == "save_intelligence":
        pass
    else:
        note_form = locals().get("note_form", LeadNoteForm())
        intelligence_form = locals().get("intelligence_form", LeadIntelligenceForm(instance=lead))
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
    lead_import = get_object_or_404(LeadImport.objects.select_related("uploaded_by"), pk=pk)
    lead_ids = lead_import.activities.values_list("lead_id", flat=True)
    leads = internal_leads_for_user(request.user).filter(pk__in=lead_ids).select_related("assigned_to").order_by("-needs_review", "-created_at")
    return render(request, "crm/import_detail.html", {
        "lead_import": lead_import,
        "page_obj": paginate(request, leads, 75),
    })


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
    return render(request, "crm/lead_queue.html", {
        "queue_type": queue_type,
        "title": titles[queue_type],
        "page_obj": paginate(request, leads.order_by("follow_up_date", "-lead_temperature", "-created_at"), 50),
    })


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
        form = LeadForm(request.POST, instance=lead)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.lead_type = "internal_sales"
            updated.client = None
            updated.ai_instance = None
            updated.save()
            messages.success(request, "Lead updated.")
            return redirect("lead_detail", pk=lead.pk)
    else:
        form = LeadForm(instance=lead)
    return render(request, "crm/lead_form.html", {"form": form, "lead": lead})


@employee_required
def lead_delete(request, pk):
    lead = get_object_or_404(Lead.objects.filter(lead_type="internal_sales", archived=False), pk=pk)
    if not can_delete_internal_leads(request.user):
        messages.error(request, "Only admins and owners can delete internal leads.")
        return redirect("lead_detail", pk=lead.pk)
    if request.method != "POST":
        messages.error(request, "Use the delete button on the lead page to remove a lead.")
        return redirect("lead_detail", pk=lead.pk)

    lead.archived = True
    lead.save(update_fields=["archived"])
    LeadActivity.objects.create(
        lead=lead,
        user=request.user,
        raw_note="Lead deleted from active CRM.",
        cleaned_note="Lead deleted from active CRM.",
        inferred_status=lead.status,
        lead_temperature=lead.lead_temperature,
        activity_type="status_change",
        classification_source="manual",
        manually_reviewed=True,
    )
    log_activity(
        user=request.user,
        request=request,
        action="delete",
        model_label="crm.Lead",
        object_id=lead.pk,
        object_repr=str(lead),
        message="Archived internal sales lead from active CRM.",
    )
    messages.success(request, "Lead deleted from active CRM.")
    return redirect("crm_home")
