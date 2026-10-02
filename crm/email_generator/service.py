import json
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from assistant_ai.services import PlatformAIService
from audit.utils import log_activity
from core.rate_limits import consume_budget
from crm.models import OutreachMessage, LeadActivity, SalesEmailConfig
from crm.sales import INACTIVE
from .context import assemble, sender_for, links_for
from .policy import POLICY, EmailError, validate_text

VERSION='sales-email-1'

def draft_schema(service_ids):
    references = {'type':'array', 'items':{'type':'string'}}
    if service_ids:
        references['items']['enum'] = service_ids
    else:
        references['maxItems'] = 0
    return {
        'type':'object', 'additionalProperties':False,
        'properties':{
            'subjects':{'type':'array','items':{'type':'string'},'minItems':3,'maxItems':3},
            'body':{'type':'string'},
            'services_referenced':references,
        },
        'required':['subjects','body','services_referenced'],
    }

def provider_failure(meta):
    category = meta.get('category') or {
        'missing_api_key': 'configuration', 'daily_limit': 'daily_limit',
        'PermissionDeniedError': 'permission', 'AuthenticationError': 'authentication',
        'NotFoundError': 'model_access', 'APITimeoutError': 'timeout',
        'APIConnectionError': 'connection', 'RateLimitError': 'rate_limit',
        'BadRequestError': 'request',
    }.get(meta.get('reason'), 'unavailable')
    messages = {
        'configuration': 'Email AI is not configured on the server. Ask your administrator to configure the existing OpenAI connection.',
        'authentication': 'OpenAI rejected the server’s API key. Your administrator needs to check the key in Render.',
        'permission': 'OpenAI denied access to email generation. Your administrator needs to check the server API key’s permissions and model access.',
        'model_access': 'The configured email AI model is unavailable to this API key. Your administrator needs to check model access in OpenAI.',
        'quota': 'The OpenAI account has reached its credit or spending limit. Your administrator needs to review API billing and limits.',
        'daily_limit': 'The site’s daily AI allowance has been reached. Try again after it resets or ask your administrator to review the limit.',
        'rate_limit': 'OpenAI is temporarily limiting requests. Wait a moment, then try again.',
        'timeout': 'OpenAI took too long to respond. Please try again.',
        'connection': 'The server could not connect to OpenAI. Please try again in a moment.',
        'request': 'OpenAI could not accept the email AI configuration. Your administrator needs to review the recorded AI error.',
    }
    if category not in messages:
        category = 'unavailable'
    message = messages.get(category, 'The AI service is temporarily unavailable. Please try again shortly.')
    return EmailError(message + ' Your selections are preserved in this tab.', 503, 'ai_' + category)

def event(user, lead, kind, message=None, **metadata):
    log_activity(user=user,action='assistant',model_label='crm.OutreachMessage',object_id=message.pk if message else '',message=kind,metadata={'lead_id':lead.pk, 'feature':'sales_email',**metadata})

def check_active(lead):
    from crm.business_status import contact_blocked
    if lead.archived or lead.status in INACTIVE or contact_blocked(lead):
        raise EmailError('This lead is closed, restricted or has closure evidence. Review its record before drafting outreach.',403)
    config=SalesEmailConfig.objects.get(pk=1)
    if not config.enabled:
        raise EmailError('Email generation is currently disabled by your manager.',403)
    return config

def serialize(m):
    return {'id':str(m.pk),'employee_id':m.employee_id,'subject':m.subject,'subjects':m.subjects,'body':m.body,'signature':m.signature,'recipient':m.recipient,'sender':m.sender,'status':m.status,'saved':bool(m.saved_at),'revision':m.revision,'options':m.generation_options,'created_at':m.created_at.isoformat(),'employee':m.employee.get_full_name() or m.employee.username if m.employee else 'Former employee','feedback':m.feedback,'feedback_reason':m.feedback_reason}

def generate(lead,user,data):
    config=check_active(lead)
    if not consume_budget('sales-email',str(user.pk),limit=30,window=3600):
        raise EmailError('You’ve reached the hourly generation limit. Try again later.',429)
    email_type=data['email_type']; selected=list(data['services'])
    # Preserve employee selection order for the final tie-breaker.
    options={k:data[k] for k in ['focus','include_demo','include_assessment','tone','length','instructions']}
    options.update(email_type=email_type.slug, services=[s.slug for s in selected])
    parent=None
    if data.get('parent'):
        parent=OutreachMessage.objects.filter(pk=data['parent'],lead=lead,employee=user,generator_version=VERSION).first()
        if not parent:
            raise EmailError('The previous draft is unavailable.',404)
    context,sender,links=assemble(lead,user,options,selected)
    options['recipient_name']=lead.point_of_contact
    options['sender_name']=sender['name']
    context['approved_links']=links
    if parent:
        from .context import clean
        context['previous_draft_for_revision'] = {'subject':clean(parent.subject,180),'body':clean(parent.body,5000),'instruction':'Revise this employee-edited draft using the current choices. This draft is NOT evidence that an email was sent.'}
    messages=[{'role':'system','content':POLICY+'\nApproved company description: '+config.company_description+'\nAssessment: '+config.assessment_description+'\nEmail type guidance: '+email_type.guidance+'\nAdditional forbidden phrases: '+config.forbidden_claims}, {'role':'user','content':json.dumps(context)}]
    service=PlatformAIService(user=user,assistant_role='sales_email')
    service.timeout=18; service.max_retries=0; service.max_completion_tokens=1300
    model=settings.SALES_EMAIL_MODEL
    schema = draft_schema(options['services'])
    hint = json.dumps({'subjects':['one','two','three'],'body':'plain email text without signature','services_referenced':options['services']})
    for attempt in range(2):
        result,meta=service.structured_json(messages=messages,schema_hint=hint,json_schema=schema,model=model,temperature=.35,fallback={},metadata={'lead_id':lead.pk,'attempt':attempt+1})
        if meta.get('status') not in ('success',) and meta.get('reason')!='invalid_json':
            error = provider_failure(meta)
            event(user,lead,'EMAIL_GENERATION_FAILED',code=error.code)
            raise error
        try:
            if not isinstance(result,dict) or set(result)!={'subjects','body','services_referenced'} or not isinstance(result['subjects'],list) or len(result['subjects'])!=3 or len(set(str(s).casefold() for s in result['subjects']))!=3 or not isinstance(result['services_referenced'],list) or any(x not in options['services'] for x in result['services_referenced']):
                raise EmailError('Invalid structured draft.',code='structure')
            validate_text(result['subjects'],result['body'],sender['signature'],links=links,forbidden=config.forbidden_claims,email_type=email_type.slug,require_links=True,length=options['length'])
            break
        except EmailError as exc:
            event(user,lead,'EMAIL_VALIDATION_FAILED',code=exc.code,attempt=attempt+1,model=model)
            if attempt:
                raise EmailError('Email generation needs review. Please regenerate.',422,'validation')
            messages.append({'role':'system','content':'The previous attempt failed validation: '+exc.code+'. Create a fresh compliant draft; correct this issue. Return the required JSON only.'})
    # Ownership might change while the provider is responding.
    from crm.views import internal_leads_for_user
    with transaction.atomic():
        if not internal_leads_for_user(user).select_for_update().filter(pk=lead.pk).exists():
            raise EmailError('Your access to this lead has changed.',403)
        lead.refresh_from_db(); check_active(lead)
        m=OutreachMessage.objects.create(lead=lead,employee=user,channel='email',recipient=lead.email,sender=sender['email'],subject=result['subjects'][0],subjects=result['subjects'],body=result['body'],signature=sender['signature'],original_output=result,generation_options=options,generator_model=model,validation_result='passed',generator_version=VERSION,parent=parent)
        event(user,lead,'EMAIL_REGENERATED' if parent else 'EMAIL_GENERATED',m,email_type=email_type.slug,services=options['services'],tone=options['tone'],length=options['length'],model=model,validation='passed')
        for key,kind in [('demo','DEMO_LINK_INCLUDED'),('assessment','GROWTH_ASSESSMENT_LINK_INCLUDED')]:
            if links[key]: event(user,lead,kind,m)
    return m

def update_draft(m,user,data):
    """Called with row lock; optimistic revision prevents silent tab overwrites."""
    if m.employee_id!=user.pk:
        raise EmailError('Only the author can edit or mark this draft sent.',403)
    if data.get('action')=='sent' and m.status=='marked_sent':
        return m
    if m.revision!=data.get('revision'):
        raise EmailError('This draft changed in another window. Reopen its latest version before editing.',409)
    action=data.get('action')
    if action=='sent' and m.status=='marked_sent':
        return m
    if m.status!='draft':
        raise EmailError('This version is read-only. Generate a new draft to continue.',409)
    config=check_active(m.lead)
    if action=='copied':
        if data.get('copy_part') not in ('copy_subject','copy_email','copy_all'):
            raise EmailError('Choose what was copied.')
        event(user,m.lead,'EMAIL_COPIED',m,part=data['copy_part'])
        return m
    if action not in ['edit','save','copy_subject','copy_email','copy_all','sent','discard','feedback']:
        raise EmailError('Choose a supported draft action.')
    if action=='feedback':
        if data.get('feedback') not in ('good','needs_work') or data.get('feedback_reason','') not in ('','Too long','Too generic','Wrong focus','Incorrect information','Bad tone','Other'):
            raise EmailError('Choose a feedback option.')
        m.feedback=data['feedback']; m.feedback_reason=data.get('feedback_reason','')
    elif action!='discard':
        subject=data.get('subject',m.subject); body=data.get('body',m.body); signature=data.get('signature',m.signature)
        if not all(isinstance(x,str) for x in [subject,body,signature]) or not 1<=len(subject)<=180 or not 1<=len(body)<=7000 or len(signature)>1200:
            raise EmailError('Check the subject, body and signature lengths.')
        # Edits are autosaved verbatim, but copy/save/sent require policy validation.
        if action!='edit':
            links=links_for(m.lead,sender_for(user),m.generation_options)
            validate_text([subject],body,signature,links=links,forbidden=config.forbidden_claims,email_type=m.generation_options['email_type'])
        m.subject,m.body,m.signature=subject,body,signature
    if action=='save':
        m.saved_at=timezone.now()
    elif action=='discard':
        m.status='discarded'
    elif action=='sent':
        m.status='marked_sent';m.sent_at=timezone.now();m.saved_at=m.saved_at or m.sent_at
        note=f'Employee manually marked email sent (delivery not verified).\nTo: {m.recipient or "Not recorded"}\nSubject: {m.subject}\n\n{m.body}\n\n{m.signature}'
        m.activity=LeadActivity.objects.create(lead=m.lead,user=user,activity_type='email',raw_note=note,cleaned_note=note,classification_source='manual',manually_reviewed=True,inferred_status=m.lead.status,metadata={'sales_email_id':str(m.pk),'delivery_verified':False})
    m.revision+=1;m.save()
    kinds={'save':'EMAIL_SAVED','sent':'EMAIL_MARKED_SENT','discard':'EMAIL_DISCARDED','feedback':'EMAIL_FEEDBACK'}
    if action in kinds: event(user,m.lead,kinds[action],m,action=action,feedback=m.feedback,saved=bool(m.saved_at))
    return m
