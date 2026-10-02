import json
from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import Count
from django.http import JsonResponse, HttpResponseGone
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from core.permissions import employee_required
from crm.views import get_internal_lead_or_404, is_sales_manager, internal_leads_for_user
from crm.models import OutreachMessage, SalesEmailConfig, SalesEmailType, SalesEmailService, SalesProfile
from audit.models import ActivityLog
from .forms import GenerationForm, ConfigForm, ProfileForm
from .context import sender_for, suggestions
from .service import generate, serialize, update_draft, event, VERSION
from .policy import EmailError


def payload(request):
    if len(request.body)>24000:
        raise EmailError('The draft is too large.',413)
    try:
        data=json.loads(request.body)
        if not isinstance(data,dict): raise ValueError
        return data
    except (ValueError,UnicodeDecodeError):
        raise EmailError('Send a valid draft request.')

def failure(exc):
    return JsonResponse({'error':str(exc),'code':exc.code},status=exc.status)

@employee_required
@never_cache
@require_GET
def page(request,pk):
    lead=get_internal_lead_or_404(request.user,pk)
    config=SalesEmailConfig.objects.get(pk=1)
    initial={'email_type':'cold','focus':'general','tone':config.default_tone,'length':config.default_length or 'short','include_demo':config.include_demo,'include_assessment':config.include_assessment}
    history=OutreachMessage.objects.filter(lead=lead,generator_version=VERSION).select_related('employee')[:50]
    event(request.user,lead,'EMAIL_GENERATOR_OPENED')
    return render(request,'crm/email_generator.html',{'lead':lead,'form':GenerationForm(initial=initial),'sender':sender_for(request.user),'config':config,'history':[serialize(m) for m in history],'suggestions':suggestions(lead),'type_lengths':dict(SalesEmailType.objects.filter(enabled=True).values_list('slug','default_length')),'manager':is_sales_manager(request.user)})

@employee_required
@never_cache
@require_POST
def create(request,pk):
    lead=get_internal_lead_or_404(request.user,pk)
    try:
        data=payload(request)
        form=GenerationForm(data)
        if not form.is_valid():
            return JsonResponse({'error':'Check the highlighted email options.','fields':form.errors},status=400)
        return JsonResponse({'draft':serialize(generate(lead,request.user,form.cleaned_data))})
    except EmailError as exc:
        return failure(exc)

@employee_required
@never_cache
@require_POST
def action(request,pk,message_id):
    get_internal_lead_or_404(request.user,pk)
    try:
        data=payload(request)
        with transaction.atomic():
            # Lead row and draft row locks serialize assignment/access and edits.
            get_object_or_404(internal_leads_for_user(request.user).select_for_update(),pk=pk)
            # employee is nullable: PostgreSQL cannot lock the nullable side of
            # its outer join. The lead is locked above; lock only this draft.
            m=get_object_or_404(OutreachMessage.objects.select_for_update(of=('self',)).select_related('lead','employee'),pk=message_id,lead_id=pk,generator_version=VERSION)
            return JsonResponse({'draft':serialize(update_draft(m,request.user,data))})
    except EmailError as exc:
        return failure(exc)

@employee_required
@never_cache
def manage(request):
    if not is_sales_manager(request.user):
        return JsonResponse({'error':'Manager access required.'},status=403)
    if request.method not in ('GET','POST'):
        return JsonResponse({'error':'Method not allowed.'},status=405)
    config=SalesEmailConfig.objects.get(pk=1)
    ServiceSet=forms.modelformset_factory(SalesEmailService,fields=['name','description','enabled','position'],extra=0,widgets={'description':forms.Textarea(attrs={'rows':2})})
    TypeSet=forms.modelformset_factory(SalesEmailType,fields=['name','guidance','default_length','enabled','position'],extra=0,widgets={'guidance':forms.Textarea(attrs={'rows':2})})
    ProfileSet=forms.modelformset_factory(SalesProfile,form=ProfileForm,extra=1)
    data=request.POST if request.method=='POST' else None
    form=ConfigForm(data,instance=config)
    services=ServiceSet(data,prefix='services');types=TypeSet(data,prefix='types');profiles=ProfileSet(data,prefix='profiles')
    # Model formsets add the existing primary key as a hidden identity field.
    if request.method=='POST' and all([form.is_valid(),services.is_valid(),types.is_valid(),profiles.is_valid()]):
        with transaction.atomic():
            form.save();services.save();types.save();profiles.save()
        from audit.utils import log_activity
        log_activity(user=request.user,request=request,action='update',model_label='crm.SalesEmailConfig',message='Updated approved sales email configuration')
        messages.success(request,'Email generator settings saved.')
        return redirect('sales_email_manage')
    drafts=OutreachMessage.objects.filter(generator_version=VERSION).select_related('employee','lead')
    stats={'generated':drafts.count(),'regenerated':drafts.filter(parent__isnull=False).count(),'saved':drafts.filter(saved_at__isnull=False).count(),'sent':drafts.filter(status='marked_sent').count(),'good':drafts.filter(feedback='good').count(),'needs work':drafts.filter(feedback='needs_work').count()}
    return render(request,'crm/email_manage.html',{'form':form,'services':services,'types':types,'profiles':profiles,'stats':stats,'drafts':drafts[:60],'event_counts':ActivityLog.objects.filter(metadata__feature='sales_email').values('message').annotate(total=Count('pk')).order_by('message')})

@never_cache
def deferred(request,**kwargs):
    return HttpResponseGone('Direct sending and Gmail connections are deferred. Use Generate email on a CRM lead to review and copy your draft.')
