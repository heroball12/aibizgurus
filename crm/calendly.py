"""Authenticated Calendly intake with idempotent, attributed CRM updates."""
import hashlib
import hmac
import time
from urllib.parse import urlencode, urlsplit
from uuid import uuid5, NAMESPACE_URL

import requests
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from audit.models import EmployeeLeadEvent
from .models import Lead, LeadActivity, AssessmentBooking, CalendlyConnection
from .sales import BOOKING_URL, INACTIVE


class CalendarError(Exception):
    pass


def booking_url(lead, user=None):
    actor = user if user and user.is_employee_or_admin() else lead.assigned_to
    token = signing.dumps({'lead':lead.pk, 'rep':actor.pk if actor else None}, salt='assessment-attribution', compress=True)
    return BOOKING_URL + '?' + urlencode({'utm_source':'aibiz-crm', 'utm_medium':'sales', 'utm_content':token})


def verify_signature(body, header):
    key = settings.CALENDLY_WEBHOOK_SIGNING_KEY
    if not key:
        return False
    try:
        fields = [part.strip().split('=', 1) for part in header.split(',')]
        stamp = next(value for name,value in fields if name == 't')
        signatures = [value for name,value in fields if name == 'v1']
        if abs(time.time() - int(stamp)) > 180:
            return False
        expected = hmac.new(key.encode(), stamp.encode() + b'.' + body, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(expected, value) for value in signatures)
    except (ValueError, StopIteration, TypeError):
        return False


def api(method, path, **kwargs):
    if not settings.CALENDLY_API_TOKEN:
        raise CalendarError('Add CALENDLY_API_TOKEN to the server environment first.')
    try:
        response = requests.request(method, 'https://api.calendly.com' + path, headers={'Authorization':'Bearer ' + settings.CALENDLY_API_TOKEN}, timeout=(4, 8), allow_redirects=False, **kwargs)
        if response.status_code in {401,403}:
            raise CalendarError('Calendly denied access. Check the token permissions and that this account has a webhook-enabled paid plan.')
        if not 200 <= response.status_code < 300:
            raise CalendarError('Calendly could not complete the connection. Please retry shortly.')
        return response.json() if response.content else {}
    except (requests.RequestException, ValueError):
        raise CalendarError('Calendly did not respond. Your existing connection has been preserved.') from None


@transaction.atomic
def connect():
    base = settings.PUBLIC_BASE_URL.rstrip('/')
    if not base.startswith('https://') or urlsplit(base).hostname in {'localhost','127.0.0.1'}:
        raise CalendarError('Set PUBLIC_BASE_URL to your public HTTPS site before connecting.')
    if len(settings.CALENDLY_WEBHOOK_SIGNING_KEY) < 32:
        raise CalendarError('Set CALENDLY_WEBHOOK_SIGNING_KEY to a random secret of at least 32 characters.')
    CalendlyConnection.objects.get_or_create(pk=1)
    connection = CalendlyConnection.objects.select_for_update().get(pk=1)
    fingerprint = hashlib.sha256(settings.CALENDLY_WEBHOOK_SIGNING_KEY.encode()).hexdigest()
    me = api('GET', '/users/me')['resource']
    event_types = api('GET','/event_types', params={'user':me['uri'], 'active':'true', 'count':100})['collection']
    event_type = next((event for event in event_types if event.get('scheduling_url','').rstrip('/') == BOOKING_URL), None)
    if not event_type:
        raise CalendarError('The token must belong to James’s account and have access to the james-aibiz/30min event.')
    endpoint = base + '/crm/assessments/calendly/webhook/'
    existing = api('GET','/webhook_subscriptions', params={'organization':me['current_organization'], 'user':me['uri'], 'scope':'user', 'count':100})['collection']
    subscription = next((item for item in existing if item.get('callback_url',item.get('url')) == endpoint and item.get('state') == 'active'), None)
    if subscription and (subscription['uri'] != connection.subscription_uri or fingerprint != connection.signing_fingerprint):
        raise CalendarError('A subscription already exists for this endpoint. Verify its signing key in Calendly before replacing or reconnecting it.')
    if not subscription:
        subscription = api('POST', '/webhook_subscriptions', json={'url':endpoint, 'events':['invitee.created','invitee.canceled'], 'organization':me['current_organization'], 'user':me['uri'], 'scope':'user', 'signing_key':settings.CALENDLY_WEBHOOK_SIGNING_KEY})['resource']
    connection.signing_fingerprint = fingerprint
    connection.subscription_uri = subscription['uri']
    connection.user_uri, connection.organization_uri = me['uri'], me['current_organization']
    connection.event_type_uri = event_type['uri']
    connection.connected_at = timezone.now()
    connection.save()
    return connection


def date(value):
    parsed = parse_datetime(value or '')
    if not parsed or timezone.is_naive(parsed):
        raise ValueError('Missing provider timestamp')
    return parsed


def match_lead(payload):
    token = (payload.get('tracking') or {}).get('utm_content')
    if token:
        try:
            identity = signing.loads(token, salt='assessment-attribution', max_age=60*60*24*180)
            lead = Lead.objects.select_related('assigned_to').get(pk=identity['lead'], lead_type='internal_sales')
            from django.contrib.auth import get_user_model
            rep = get_user_model().objects.filter(pk=identity.get('rep'), is_active=True, role__in=['employee','admin','owner']).first()
            if lead.email and lead.email.strip().casefold() != payload.get('email','').strip().casefold():
                return None, None, 'Booking email differs from the linked lead. Review the match.'
            return lead, rep, ''
        except (signing.BadSignature, Lead.DoesNotExist, KeyError, TypeError, ValueError):
            return None, None, 'The lead tracking link is invalid or expired. Review the match.'
    email = payload.get('email','').strip()
    leads = list(Lead.objects.select_related('assigned_to').filter(lead_type='internal_sales', email__iexact=email)[:2]) if email else []
    if len(leads) == 1:
        return leads[0], leads[0].assigned_to, ''
    return None, None, 'No unique CRM email match. Select the correct lead.'


def apply_booking(booking):
    if not booking.lead_id:
        return
    lead = Lead.objects.select_for_update().get(pk=booking.lead_id)
    if lead.archived or lead.status in INACTIVE or lead.status in {'appointment_completed','proposal_requested','proposal_sent'}:
        booking.review_reason = 'Lead is archived, restricted or already past assessment. Review without reopening outreach.'
        booking.save(update_fields=['review_reason'])
        return
    brief = dict(lead.assessment_brief or {})
    current_uri = brief.get('calendly_invitee')
    if booking.status == 'active':
        superseding = AssessmentBooking.objects.filter(old_invitee_uri=booking.invitee_uri).exists()
        if superseding:
            booking.review_reason = 'Superseded by a rescheduled booking.'
            booking.save(update_fields=['review_reason'])
            return
        if current_uri and current_uri != booking.invitee_uri and current_uri != booking.old_invitee_uri:
            current = AssessmentBooking.objects.filter(invitee_uri=current_uri).first()
            if current and current.status == 'active':
                booking.review_reason = 'Another active assessment exists for this lead. Review the newer booking.'
                booking.save(update_fields=['review_reason'])
                return
        if lead.appointment_at and not current_uri and lead.appointment_at != booking.starts_at:
            booking.review_reason = 'A different manually recorded assessment exists. Review the match.'
            booking.save(update_fields=['review_reason'])
            return
        lead.appointment_at = booking.starts_at
        lead.status = 'appointment_scheduled'
        lead.follow_up_date = lead.next_follow_up_at = None
        brief.update(calendly_invitee=booking.invitee_uri, meeting_url=booking.meeting_url)
    elif current_uri == booking.invitee_uri:
        lead.appointment_at = None
        lead.status = 'follow_up'
        lead.follow_up_date = timezone.localdate()
        lead.next_follow_up_at = timezone.now()
        brief.pop('calendly_invitee', None)
        brief.pop('meeting_url', None)
    else:
        booking.applied_at = timezone.now()
        booking.review_reason = ''
        booking.save(update_fields=['applied_at','review_reason'])
        return
    lead.assessment_brief = brief
    lead.save()
    event_key = uuid5(NAMESPACE_URL, 'calendly:' + booking.invitee_uri + ':' + booking.status)
    event, created = EmployeeLeadEvent.objects.get_or_create(request_key=event_key, lead_key=lead.pk, defaults={
        'actor':booking.credited_to, 'actor_name':(booking.credited_to.get_full_name() or booking.credited_to.username)[:150] if booking.credited_to else 'Unattributed booking',
        'lead':lead, 'lead_name':(lead.business_name or lead.name)[:200], 'kind':'updated', 'source':'calendly', 'status':lead.status,
        'assessment_booked':booking.status == 'active', 'counts_as_call':False, 'changes':{'calendar':{'before':'','after':'Assessment booked' if booking.status=='active' else 'Assessment canceled'}}})
    if created:
        EmployeeLeadEvent.objects.filter(pk=event.pk).update(created_at=booking.provider_updated_at)
        LeadActivity.objects.create(lead=lead, user=booking.credited_to, activity_type='status_change', raw_note='Calendly: assessment ' + ('booked.' if booking.status=='active' else 'canceled; follow-up needed.'), inferred_status=lead.status, metadata={'provider':'calendly'})
    booking.applied_at = timezone.now()
    booking.review_reason = ''
    booking.save(update_fields=['applied_at','review_reason'])


@transaction.atomic
def receive(data):
    if data.get('event') not in {'invitee.created','invitee.canceled'}:
        return 'ignored'
    payload = data['payload']
    scheduled = payload['scheduled_event']
    connection = CalendlyConnection.objects.select_for_update().filter(pk=1).first()
    if not connection or not connection.event_type_uri:
        raise CalendarError('Connection has not been configured.')
    connection.last_received_at = timezone.now()
    connection.save(update_fields=['last_received_at'])
    if scheduled.get('event_type') != connection.event_type_uri:
        return 'ignored'
    uri = payload['uri']
    event_uri = payload['event']
    if not uri.startswith('https://api.calendly.com/scheduled_events/') or not event_uri.startswith('https://api.calendly.com/scheduled_events/'):
        raise ValueError('Invalid provider reference')
    updated = date(payload.get('updated_at') or data.get('created_at'))
    booking = AssessmentBooking.objects.select_for_update().filter(invitee_uri=uri).first()
    if booking and booking.provider_updated_at >= updated:
        return 'duplicate'
    lead, rep, reason = match_lead(payload)
    if booking and booking.lead_id:
        lead, rep, reason = booking.lead, booking.credited_to, ''
    old_uri = payload.get('old_invitee') or ''
    if not lead and old_uri:
        old = AssessmentBooking.objects.filter(invitee_uri=old_uri, lead__isnull=False).first()
        if old:
            lead, rep, reason = old.lead, old.credited_to, ''
    location = scheduled.get('location') or {}
    meeting = location.get('join_url') or ''
    if not meeting.startswith('https://'):
        meeting = ''
    values = dict(event_uri=event_uri, old_invitee_uri=old_uri, lead=lead, credited_to=rep, email=payload.get('email','')[:254], name=payload.get('name','')[:200],
                  starts_at=date(scheduled.get('start_time')), status='canceled' if data['event']=='invitee.canceled' or payload.get('status')=='canceled' else 'active', provider_updated_at=updated,
                  meeting_url=meeting[:1000], review_reason=reason, applied_at=None)
    booking, _ = AssessmentBooking.objects.update_or_create(invitee_uri=uri, defaults=values)
    apply_booking(booking)
    return 'received'
