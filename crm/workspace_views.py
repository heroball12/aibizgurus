from datetime import datetime, time

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest
from .lead_finder import public_url
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from audit.utils import log_activity
from .forms import AssessmentForm, LeadIntelligenceForm, LeadNoteForm, SalesUpdateForm
from .models import Lead, LeadActivity
from .sales import STAGES, INACTIVE, ASSESSMENT_DESCRIPTION, BOOKING_URL, annotate_leads, due_filter, guide_url, playbook, stage_for
from .views import employee_required, internal_leads_for_user, get_internal_lead_or_404, is_sales_manager, paginate, query_without_page


def detail_context(lead):
    brief = lead.assessment_brief or {}
    return {
        "lead": lead, "safe_website": public_url(lead.website), "sales_stage": stage_for(lead)[1], "contact_blocked": lead.status in INACTIVE,
        "playbook": playbook(lead), "guru_url": guide_url(lead), "booking_url": BOOKING_URL,
        "sales_form": SalesUpdateForm(initial={"follow_up_date":lead.follow_up_date}, prefix="outcome"),
        "assessment_form": AssessmentForm(prefix="assessment", initial={**brief,"appointment_at":lead.appointment_at,"confirmed":bool(lead.appointment_at),"completed":lead.status in STAGES[4][2]}),
    }


@employee_required
def pipeline(request):
    base = internal_leads_for_user(request.user).select_related("assigned_to")
    leads = base
    stage = request.GET.get("stage", "all")
    if stage not in {key for key, _, _ in STAGES} | {"all", "due"}:
        stage = "all"
    query = request.GET.get("q", "").strip()[:200]
    if stage == "due":
        leads = leads.exclude(status__in=INACTIVE).filter(due_filter())
    else:
        statuses = next((items for key, _, items in STAGES if key == stage), None)
        if statuses is not None:
            leads = leads.filter(status__in=statuses)
    if query:
        leads = leads.filter(Q(business_name__icontains=query)|Q(name__icontains=query)|Q(phone__icontains=query)|Q(email__icontains=query))
    counts = base.aggregate(**{key:Count("pk",filter=Q(status__in=items)) for key,_,items in STAGES})
    page = paginate(request, leads.order_by("-created_at"), 25)
    annotate_leads(page.object_list)
    return render(request,"crm/pipeline.html",{
        "page_obj":page,"stages":[{"key":key,"label":label,"count":counts[key]} for key,label,_ in STAGES],
        "stage":stage,"q":query,"query_string":query_without_page(request),"guru_url":guide_url(),
    })


@employee_required
def assessments(request):
    leads = internal_leads_for_user(request.user).filter(status__in=STAGES[3][2]+STAGES[4][2]).order_by("appointment_at","-created_at")
    page = paginate(request, leads, 20)
    annotate_leads(page.object_list)
    return render(request,"crm/assessments.html",{"page_obj":page,"description":ASSESSMENT_DESCRIPTION,"booking_url":BOOKING_URL,"guru_url":guide_url(),"query_string":query_without_page(request)})


@employee_required
@require_POST
def lead_progress(request, pk):
    lead = get_internal_lead_or_404(request.user,pk)
    action = request.POST.get("action")
    if action not in {"assessment", "progress"}:
        return HttpResponseBadRequest("Choose a valid sales action.")
    form = AssessmentForm(request.POST, prefix="assessment") if action == "assessment" else SalesUpdateForm(request.POST, prefix="outcome")
    if form.is_valid():
        with transaction.atomic():
            lead = internal_leads_for_user(request.user).select_for_update().get(pk=pk)
            before = lead.status
            if action == "assessment":
                data = form.cleaned_data
                if lead.status == "do_not_contact":
                    form.add_error(None,"This lead is marked do not contact. A manager must review that restriction before an assessment can be recorded.")
                else:
                    lead.assessment_brief = {k:v for k,v in data.items() if k not in {"appointment_at","confirmed","completed"}}
                    lead.appointment_at = data["appointment_at"]
                    if data["confirmed"]:
                        lead.status = (before if before in {"proposal_requested", "proposal_sent"} else "appointment_completed") if data["completed"] else "appointment_scheduled"
                        lead.follow_up_date = None
                        lead.next_follow_up_at = None
                    elif before in STAGES[3][2] + STAGES[4][2]:
                        lead.status = "follow_up"
                    note = "Growth Assessment brief updated." + (" Confirmed booking recorded." if data["confirmed"] else " No booking recorded.")
            else:
                data = form.cleaned_data
                if lead.status == "do_not_contact" and data["outcome"] != "do_not_contact":
                    form.add_error(None,"A manager must review the do-not-contact restriction before outreach resumes.")
                else:
                    lead.status = data["outcome"]
                    lead.follow_up_date = data["follow_up_date"] if lead.status not in INACTIVE else None
                    lead.next_follow_up_at = timezone.make_aware(datetime.combine(lead.follow_up_date, time(9))) if lead.follow_up_date else None
                    if lead.status not in {"do_not_contact","closed_won"}:
                        lead.last_contact_at = timezone.now()
                    if lead.status == "warm_lead":lead.lead_temperature = "warm"
                    if lead.status in INACTIVE:lead.lead_temperature = "closed"
                    note = data["note"] or "Sales outcome updated."
            if not form.errors:
                lead.save()
                LeadActivity.objects.create(lead=lead,user=request.user,raw_note=note,cleaned_note=note,inferred_status=lead.status,lead_temperature=lead.lead_temperature,activity_type="status_change",classification_source="manual",manually_reviewed=True,metadata={"previous_status":before,"workspace_action":action})
                log_activity(user=request.user,request=request,action="update",model_label="crm.Lead",object_id=lead.pk,object_repr=str(lead),message=note[:255])
                messages.success(request,"Assessment saved." if action=="assessment" else "Outcome saved. Your next step is ready.")
                return redirect("lead_detail",pk=pk)
    context = detail_context(lead)
    context.update({"assessment_form" if action=="assessment" else "sales_form":form,"note_form":LeadNoteForm(),"intelligence_form":LeadIntelligenceForm(instance=lead,user=request.user,is_sales_manager=is_sales_manager(request.user)),"activities":lead.activities.select_related("user")[:25],"can_delete_lead":is_sales_manager(request.user)})
    return render(request,"crm/lead_detail.html",context,status=400)
