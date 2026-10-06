"""Recover provable, pre-counter CRM activity. Never infer work from ownership."""
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from django.db import transaction
from django.db.migrations.recorder import MigrationRecorder
from django.urls import resolve, Resolver404
from django.utils.dateparse import parse_datetime

from crm.models import Lead, LeadActivity, LeadNote
from .models import ActivityLog, EmployeeLeadEvent
from .sales_tracking import MANUAL_SOURCES

SOURCES = ('audit', 'activity', 'note')


def cutoff():
    return MigrationRecorder.Migration.objects.filter(app='audit', name='0008_employee_lead_events').values_list('applied', flat=True).first()


def route(path):
    try:
        return resolve(path).url_name
    except Resolver404:
        return ''


def request_for(actor_id, at, path=None):
    query = ActivityLog.objects.filter(actor_id=actor_id, action='request', method='POST', created_at__gte=at, created_at__lte=at + timedelta(seconds=120)).order_by('created_at', 'pk')
    if path:
        query = query.filter(path=path)
    # Failed submissions and unrelated routes are not evidence of a saved edit.
    request = query.first()
    return request if request and request.status_code and 200 <= request.status_code < 400 and route(request.path) in MANUAL_SOURCES | {'lead_create', 'lead_delete'} else None


def candidate(record, source):
    actor = record.actor if source == 'audit' else record.user
    if not actor or not actor.is_employee_or_admin():
        return None
    status = previous = ''
    kind = 'updated'
    if source == 'audit':
        if record.method != 'POST' or route(record.path) not in MANUAL_SOURCES | {'lead_create', 'lead_delete'}:
            return None
        try:
            if record.model_label == 'crm.Lead':
                key = int(record.object_id)
                lead = Lead.objects.filter(pk=key).first()
                kind = {'create':'created', 'update':'updated', 'delete':'deleted'}[record.action]
            else:
                note = LeadNote.objects.select_related('lead').filter(pk=int(record.object_id)).first()
                if not note:
                    return None
                lead, key = note.lead, note.lead_id
        except (ValueError, KeyError):
            return None
        request = request_for(actor.pk, record.created_at, record.path)
        # Without a request boundary, repeated audit messages cannot be safely deduplicated.
        if not request:
            return None
        label = record.object_repr[:200]
    else:
        lead, key, label = record.lead, record.lead_id, str(record.lead)[:200]
        if source == 'activity':
            if record.original_import_id or record.activity_type not in {'call', 'manual_note', 'status_change', 'follow_up'}:
                return None
            if record.activity_type != 'call' and record.classification_source != 'manual':
                return None
            status = record.inferred_status
            previous = record.metadata.get('previous_status', '')
        request = request_for(actor.pk, record.created_at)
        # A batch import/create is not a call even if it also emitted a note.
        if request and route(request.path) == 'lead_create':
            kind = 'created'
    if lead and lead.lead_type != 'internal_sales':
        return None
    if not lead and (source != 'audit' or not record.path.startswith('/crm/')):
        return None
    identity = f'request:{request.pk}' if request else f'{source}:{record.pk}'
    if not request and source == 'activity' and record.activity_type == 'manual_note':
        twins = list(LeadNote.objects.filter(lead_id=key, user=actor, note=record.raw_note, created_at__range=(record.created_at-timedelta(seconds=2), record.created_at+timedelta(seconds=2))).values_list('pk', flat=True)[:2])
        if len(twins) == 1:
            identity = f'note:{twins[0]}'
    appointment = record.metadata.get('appointment_at') if source == 'activity' else None
    try:
        appointment = parse_datetime(appointment) if isinstance(appointment, str) else None
    except ValueError:
        appointment = None
    return dict(request_key=uuid5(NAMESPACE_URL, 'aibiz.guru/history/v1/' + identity), lead_key=key,
                actor=actor, actor_name=(actor.get_full_name() or actor.username)[:150], lead=lead,
                lead_name=(lead.business_name or lead.name)[:200] if lead else label,
                source='historical_' + source, kind=kind, status=status, previous_status=previous,
                counts_as_call=kind == 'updated', created_at=record.created_at,
                historical=True, changes={'history':{'before':'', 'after':'Recovered from a saved historical record. Original field-by-field changes are unavailable.'}}, evidence={'source': source, 'record_id': record.pk, 'request_id': request.pk if request else None, 'confirmed_appointment_at':appointment.isoformat() if appointment else None})


def batch(source='audit', after=0, *, apply=False, limit=200, before=None):
    before = before or cutoff()
    if source not in SOURCES or not before:
        raise ValueError('The activity-counter migration must be installed before history can be recovered.')
    query = {'audit': ActivityLog.objects.select_related('actor').filter(model_label__in=['crm.Lead', 'crm.LeadNote'], action__in=['create', 'update', 'delete']),
             'activity': LeadActivity.objects.select_related('user', 'lead'),
             'note': LeadNote.objects.select_related('user', 'lead')}[source]
    records = list(query.filter(pk__gt=after, created_at__lt=before).order_by('pk')[:limit])
    report = {'scanned': len(records), 'recovered': 0, 'already_counted': 0, 'unsupported': 0}
    seen = set()
    for record in records:
        data = candidate(record, source)
        if not data:
            report['unsupported'] += 1
            continue
        at = data.pop('created_at')
        identity = (data['request_key'], data['lead_key'])
        existing = EmployeeLeadEvent.objects.filter(request_key=identity[0], lead_key=identity[1]).first()
        # Protect already-recorded modern events too (e.g. migration applied after code rollout).
        modern = EmployeeLeadEvent.objects.filter(historical=False, actor=data['actor'], lead_key=data['lead_key'], created_at__range=(at-timedelta(seconds=120), at+timedelta(seconds=120))).exists()
        if existing or identity in seen or modern:
            report['already_counted'] += 1
        else:
            report['recovered'] += 1
        seen.add(identity)
        if apply and not modern:
            with transaction.atomic():
                event, made = EmployeeLeadEvent.objects.get_or_create(request_key=identity[0], lead_key=identity[1], defaults=data)
                if made:
                    EmployeeLeadEvent.objects.filter(pk=event.pk).update(created_at=at)
                # Only a structured historical status transition can restore outcomes.
                if data['previous_status'] and data['previous_status'] != data['status']:
                    flags = {'assessment_booked': data['status'] == 'appointment_scheduled' and bool(data['evidence']['confirmed_appointment_at']), 'assessment_completed':data['status'] == 'appointment_completed' and bool(data['evidence']['confirmed_appointment_at']),
                             'proposal':data['status'] in {'proposal_requested','proposal_sent'}, 'won':data['status'] in {'closed_won','client_onboarded'}, 'lost':data['status'] == 'closed_lost'}
                    EmployeeLeadEvent.objects.filter(pk=event.pk).update(status=data['status'], previous_status=data['previous_status'], **{k:True for k,v in flags.items() if v})
    next_source, next_after = source, records[-1].pk if records else after
    if len(records) < limit:
        index = SOURCES.index(source) + 1
        next_source, next_after = (SOURCES[index], 0) if index < len(SOURCES) else ('done', 0)
    return {**report, 'next_source':next_source, 'next_after':next_after, 'cutoff':before}
