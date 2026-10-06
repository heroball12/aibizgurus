import uuid
from datetime import datetime, time
from django import forms
from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from .forms import SalesUpdateForm
from .followups import PLANS, STOP, advance, description
from .models import LeadActivity, SalesWorkSubmission, SalesFollowUpPlan
from .sales import due_filter
from .sheet_schema import version_for
from .views import employee_required, internal_leads_for_user, get_internal_lead_or_404
from .workspace_views import detail_context

class GuidedOutcomeForm(SalesUpdateForm):
    plan = forms.ChoiceField(label='Follow-up plan', required=False, choices=[('', 'Keep my current plan'), *[(key,label) for key,(label,_) in PLANS.items()], ('pause','Pause reminders')])
    ticket = forms.CharField(widget=forms.HiddenInput())
    def clean(self):
        data = super().clean()
        if data.get('outcome') == 'callback_requested' and data.get('follow_up_date') and data['follow_up_date'] < timezone.localdate():
            self.add_error('follow_up_date', 'Choose today or a future date.')
        return data


def queue(request):
    skipped = request.session.get('selling_skipped', [])
    return internal_leads_for_user(request.user).exclude(status__in=STOP).exclude(pk__in=skipped).filter(
        due_filter() | (Q(follow_up_date__isnull=True) & Q(next_follow_up_at__isnull=True))
    ).annotate(work_priority=Case(When(due_filter(), then=Value(0)), When(status__in=['hot_lead','warm_lead'], then=Value(1)), default=Value(2), output_field=IntegerField())).order_by('work_priority', 'last_contact_at', 'created_at', 'pk')


@employee_required
@never_cache
def guided_sell(request):
    lead = None
    form = None
    error_status = 200
    if request.method == 'POST':
        if request.POST.get('action') == 'reset':
            request.session['selling_skipped'] = []
            return redirect('guided_sell')
        try:
            ticket = signing.loads(request.POST.get('ticket', ''), salt='guided-selling', max_age=86400)
            if ticket['actor'] != request.user.pk:
                raise ValueError()
            lead = get_internal_lead_or_404(request.user, ticket['lead'])
        except (signing.BadSignature, KeyError, ValueError):
            messages.error(request, 'This selling session expired. Open the next lead again.')
            return redirect('guided_sell')
        if request.POST.get('action') == 'skip':
            request.session['selling_skipped'] = (request.session.get('selling_skipped', []) + [lead.pk])[-500:]
            return redirect('guided_sell')
        form = GuidedOutcomeForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                lead = get_object_or_404(internal_leads_for_user(request.user).select_for_update(), pk=lead.pk)
                if SalesWorkSubmission.objects.filter(nonce=ticket['nonce'], actor=request.user).exists():
                    return redirect('guided_sell')
                if lead.status in STOP or lead.archived or ticket['version'] != version_for(lead):
                    form.add_error(None, 'This lead changed while you were working. Review its latest details before saving again.')
                    error_status = 409
                else:
                    before = lead.status
                    data = form.cleaned_data
                    lead.status = data['outcome']
                    date = advance(lead, request.user, data['plan'], data['follow_up_date'])
                    lead.follow_up_date = date if lead.status not in STOP else None
                    lead.next_follow_up_at = timezone.make_aware(datetime.combine(lead.follow_up_date, time(9))) if lead.follow_up_date else None
                    lead.last_contact_at = timezone.now()
                    if lead.status == 'warm_lead':
                        lead.lead_temperature = 'warm'
                    if lead.status in STOP:
                        lead.lead_temperature = 'closed'
                    lead.save()
                    note = data['note'] or 'Guided selling outcome recorded.'
                    LeadActivity.objects.create(lead=lead, user=request.user, raw_note=note, cleaned_note=note, activity_type='status_change', classification_source='manual', manually_reviewed=True, inferred_status=lead.status, lead_temperature=lead.lead_temperature, metadata={'previous_status':before, 'workspace_action':'guided_sell'})
                    SalesWorkSubmission.objects.create(nonce=ticket['nonce'], lead=lead, actor=request.user)
                    request.session['selling_skipped'] = (request.session.get('selling_skipped', []) + [lead.pk])[-500:]
                    messages.success(request, 'Saved. Your next conversation is ready.')
                    return redirect('guided_sell')
        else:
            error_status = 400
    remaining = queue(request)
    lead = lead or remaining.first()
    context = {'remaining':remaining.count(), 'skipped':len(request.session.get('selling_skipped', []))}
    if lead:
        token = signing.dumps({'actor':request.user.pk, 'lead':lead.pk, 'version':version_for(lead), 'nonce':str(uuid.uuid4())}, salt='guided-selling')
        form = form or GuidedOutcomeForm(initial={'ticket':token})
        # A conflict gets a fresh ticket only after its message and current facts are shown.
        if error_status == 409:
            form.data = form.data.copy()
            form.data['ticket'] = token
        plan = SalesFollowUpPlan.objects.filter(lead=lead).first()
        context.update(detail_context(lead, request.user), outcome_form=form, followup_label=description(plan), plan=plan, activities=lead.activities.select_related('user')[:5])
    return render(request, 'crm/guided_sell.html', context, status=error_status)
