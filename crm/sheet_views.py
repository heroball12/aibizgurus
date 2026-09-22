"""Private worksheets that edit scoped CRM records, never a second copy of lead data."""
import json
import re
import uuid
from datetime import datetime, time, timedelta
from django.core import signing
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.cache import never_cache
from audit.utils import log_activity
from core.models import RequestBudget
from .models import Lead, LeadSheet, LeadStaging, LeadActivity, LeadImport
from .lead_finder import normalize_phone, lead_dedupe_key
from .sheet_schema import columns, values_for, version_for, clean_changes, BRIEF_FIELDS, MAX_ROWS, MAX_EXPORT_ROWS
from .views import (employee_required, internal_leads_for_user, lead_staging_for_user, is_sales_manager,
                    apply_lead_filters, lead_filter_values, order_leads, apply_staging_filters, lead_finder_filter_values)
from .sales import STAGES, INACTIVE, due_filter

SALT = 'crm.sheet.snapshot.v1'
FILE_SALT = 'crm.sheet.file-record.v1'


def scoped(user, kind):
    return lead_staging_for_user(user) if kind == 'prospects' else internal_leads_for_user(user)


def selection(request):
    kind = 'prospects' if request.GET.get('kind') == 'prospects' else 'leads'
    qs = scoped(request.user, kind)
    source = request.GET.get('source', 'blank')
    if source == 'blank':
        return kind, qs.none()
    if kind == 'prospects':
        return kind, apply_staging_filters(qs, lead_finder_filter_values(request)).order_by('-created_at')
    qs = apply_lead_filters(qs, lead_filter_values(request))
    if source == 'lead':
        qs = qs.filter(pk=get_object_or_404(qs, pk=request.GET.get('record', '') if request.GET.get('record', '').isdigit() else 0).pk)
    elif source == 'import':
        imports = LeadImport.objects.all()
        if not is_sales_manager(request.user):
            imports = imports.filter(uploaded_by=request.user)
        obj = get_object_or_404(imports, pk=request.GET.get('record', '') if request.GET.get('record', '').isdigit() else 0)
        qs = qs.filter(pk__in=obj.activities.values('lead_id'))
    elif source == 'assessments':
        qs = qs.filter(status__in=STAGES[3][2]+STAGES[4][2])
    elif source == 'queue':
        queue = request.GET.get('queue', '')
        if queue == 'warm': qs = qs.filter(lead_temperature__in=['warm', 'hot'])
        elif queue == 'hot': qs = qs.filter(lead_temperature='hot')
        elif queue == 'review': qs = qs.filter(needs_review=True)
        elif queue == 'followups': qs = qs.filter(Q(follow_up_date__lte=timezone.localdate()) | Q(status__in=['callback_requested','follow_up','email_requested','information_requested']))
        else: qs = qs.none()
    elif source == 'pipeline':
        stage = request.GET.get('stage', 'all')
        if stage == 'due': qs = qs.exclude(status__in=INACTIVE).filter(due_filter())
        else:
            statuses = next((items for key, _, items in STAGES if key == stage), None)
            if statuses is not None: qs = qs.filter(status__in=statuses)
    return kind, order_leads(qs, request.GET.get('sort', 'newest'))


def packet(user, sheet, records=None):
    schema = columns(user, sheet.kind)
    if records is None:
        records = {r.pk: r for r in scoped(user, sheet.kind).filter(pk__in=[r['pk'] for r in sheet.rows])}
    refs, rows = {}, []
    missing = 0
    for ref in sheet.rows:
        record = records.get(ref['pk'])
        if not record:
            missing += 1
            continue
        refs[ref['key']] = {'pk': record.pk, 'version': version_for(record)}
        rows.append({'key': ref['key'], 'values': values_for(record, schema), 'url': reverse('lead_detail', args=[record.pk]) if sheet.kind == 'leads' else reverse('lead_finder')})
    snapshot = signing.dumps({'user':user.pk, 'sheet':str(sheet.pk), 'kind':sheet.kind, 'revision':sheet.revision, 'refs':refs}, salt=SALT, compress=True)
    return {'id':str(sheet.pk), 'title':sheet.title, 'kind':sheet.kind, 'revision':sheet.revision,
            'snapshot':snapshot, 'rows':rows, 'columns':schema, 'maxRows':MAX_ROWS, 'missing':missing,
            'url':reverse('lead_sheet',args=[sheet.pk]), 'saved':sheet.revision > 0}


@employee_required
@never_cache
@require_GET
def hub(request):
    return render(request, 'crm/sheets.html', {'sheets':LeadSheet.objects.filter(owner=request.user)[:100]})


@employee_required
@never_cache
@require_GET
def editor(request, pk=None):
    total = 0
    if pk:
        sheet = get_object_or_404(LeadSheet, pk=pk, owner=request.user)
        data = packet(request.user, sheet)
    else:
        kind, qs = selection(request)
        total = qs.count()
        records = list(qs[:MAX_ROWS])
        sheet = LeadSheet(owner=request.user, kind=kind, title='Untitled lead sheet' if not total else 'Finder prospects' if kind == 'prospects' else 'Pipeline leads')
        sheet.rows = [{'key':str(uuid.uuid4()), 'pk':r.pk} for r in records]
        data = packet(request.user, sheet, {r.pk:r for r in records})
    data['total'] = total
    return render(request, 'crm/sheet_editor.html', {'sheet_data':data})


def read_snapshot(user, token):
    data = signing.loads(token, salt=SALT, max_age=7*86400)
    if data['user'] != user.pk:
        raise signing.BadSignature('Wrong user')
    return data


class SheetError(Exception):
    def __init__(self, message, errors=None, status=400):
        self.message, self.errors, self.status = message, errors or [], status


def duplicate(record, kind):
    phone = normalize_phone(record.phone_number if kind == 'prospects' else record.phone)
    for model, field in ((Lead, 'phone'), (LeadStaging, 'phone_number')):
        qs = model.objects.all()
        if model == Lead: qs = qs.filter(lead_type='internal_sales')
        if isinstance(record, model) and record.pk: qs = qs.exclude(pk=record.pk)
        if phone:
            # Match legacy formatted phone numbers without loading unrelated contacts.
            pattern = r'^\D*' + (r'(1\D*)?' if len(phone) == 10 else '') + r'\D*'.join(re.escape(c) for c in phone) + r'\D*$'
            if qs.filter(**{field+'__regex':pattern}).exists(): return True
        if record.business_name.strip() and qs.filter(business_name__iexact=record.business_name.strip(), city__iexact=record.city, state__iexact=record.state).exists(): return True
    return False


def persist(request, payload):
    try:
        snap = read_snapshot(request.user, payload.get('snapshot', ''))
        sheet_id = uuid.UUID(snap['sheet'])
        if not isinstance(payload.get('mutation_id'), str):
            raise ValueError()
        mutation = uuid.UUID(payload.get('mutation_id', ''))
    except (signing.BadSignature, ValueError, TypeError, KeyError):
        raise SheetError('This sheet session expired. Reopen the sheet before saving.', status=409)
    title = payload.get('title', '')
    rows = payload.get('rows')
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > 150:
        raise SheetError('Give your sheet a name of 1–150 characters.')
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise SheetError(f'Use up to {MAX_ROWS} rows per sheet.')
    # Share the Finder lock so promotion and sheet saves cannot create the same prospect twice.
    RequestBudget.objects.get_or_create(key='lead-staging-write-lock', defaults={'expires_at':timezone.now()+timedelta(days=36500)})
    RequestBudget.objects.select_for_update().get(pk='lead-staging-write-lock')
    sheet = LeadSheet.objects.select_for_update().filter(pk=sheet_id, owner=request.user).first()
    if sheet and sheet.last_mutation_id == mutation:
        return packet(request.user, sheet)
    if (sheet and (sheet.revision != snap['revision'] or sheet.kind != snap['kind'])) or (not sheet and snap['revision']):
        raise SheetError('This sheet was saved elsewhere. Reopen it to get the latest version; your edits have not been applied.', status=409)
    if not sheet:
        sheet = LeadSheet(id=sheet_id, owner=request.user, kind=snap['kind'])
    schema = columns(request.user, sheet.kind)
    by_key = {c['key']:c for c in schema}
    refs = snap['refs']
    records = {r.pk:r for r in scoped(request.user, sheet.kind).select_related(None).select_for_update().filter(pk__in=[r['pk'] for r in refs.values()]).order_by('pk')}
    pending, errors, seen = [], [], set()
    for index, row in enumerate(rows, 1):
        try:
            key, changes = row['key'], row['changes']
            if not isinstance(key, str): raise ValueError()
            uuid.UUID(key)
            if not isinstance(changes, dict) or key in seen: raise ValueError()
            seen.add(key)
        except (ValueError, TypeError, KeyError):
            raise SheetError('A row is invalid or repeated. Reload the sheet before saving.')
        ref = refs.get(key)
        record = records.get(ref['pk']) if ref else None
        if ref and not record:
            errors.append({'row':index,'key':key,'field':'business_name','message':'This record was removed or reassigned. Remove it from this sheet and try again.'})
            continue
        if record and changes and version_for(record) != ref['version']:
            raise SheetError(f'Row {index} changed in the CRM after this sheet opened. Reopen the sheet to review the latest data; nothing was overwritten.', status=409)
        if not record and not any(str(v).strip() for k,v in changes.items() if k not in ('status','lead_temperature','assigned_to')):
            continue
        if not record:
            if sheet.kind == 'prospects':
                raise SheetError('Add new businesses in a lead sheet. Finder sheets edit existing search results only.')
            record = Lead(assigned_to=request.user, source='Lead sheet', source_sheet=title.strip())
        cleaned, cell_errors = clean_changes(changes, schema)
        before = values_for(record, schema)
        for field, value in cleaned.items():
            if field in BRIEF_FIELDS:
                record.assessment_brief = {**(record.assessment_brief or {}), field:value}
            elif field == 'assigned_to': record.assigned_to_id = int(value) if value else None
            else: setattr(record, by_key[field]['field'], value)
        if not record.business_name.strip() and not getattr(record, 'name', '').strip():
            cell_errors['business_name'] = 'Add a business name or contact name.'
        if sheet.kind == 'leads':
            if before['status'] == 'do_not_contact' and record.status != before['status'] and not is_sales_manager(request.user):
                cell_errors['status'] = 'A manager must review the do-not-contact restriction.'
            if record.status in ('appointment_scheduled', 'appointment_completed') and record.status != before['status'] and not record.appointment_at:
                cell_errors['status'] = 'Record the confirmed Growth Assessment booking on the lead page first.'
            if 'follow_up_date' in cleaned:
                record.next_follow_up_at = timezone.make_aware(datetime.combine(record.follow_up_date, time(9))) if record.follow_up_date else None
        identity_changed = not record.pk or any(k in cleaned and str(cleaned[k]) != before.get(k, '') for k in ('business_name','phone','city','state'))
        changed = values_for(record, schema) != before or not record.pk
        errors.extend({'row':index, 'key':key, 'field':field, 'message':message} for field,message in cell_errors.items())
        pending.append((key,record,changed,identity_changed,changes,index))
    if errors: raise SheetError('Fix the highlighted cells, then save again. No records were changed.', errors)
    # Writes remain inside one transaction, including duplicate checks against earlier new rows.
    output, changes_count = [], 0
    for key, record, changed, identity_changed, changes, index in pending:
        if changed:
            if identity_changed and duplicate(record, sheet.kind):
                raise SheetError('A matching business already exists. Edit its existing row instead; no changes were saved.', [{'row':index,'key':key,'field':'business_name','message':'Matches an existing business or phone number.'}])
            key_value = lead_dedupe_key(business_name=record.business_name, phone_number=record.phone_number if sheet.kind == 'prospects' else record.phone, city=record.city, state=record.state)
            if sheet.kind == 'leads': record.duplicate_key = key_value
            else: record.dedupe_key = key_value
            record.save()
            changes_count += 1
            if sheet.kind == 'leads':
                LeadActivity.objects.create(lead=record,user=request.user,activity_type='manual_note',raw_note='Updated from lead sheet: '+title.strip(),cleaned_note='Lead data saved from spreadsheet.',inferred_status=record.status,lead_temperature=record.lead_temperature,classification_source='manual',manually_reviewed=True,metadata={'sheet':str(sheet.pk),'fields':list(changes)})
        output.append({'key':key,'pk':record.pk})
    sheet.title, sheet.rows = title.strip(), output
    sheet.revision += 1
    sheet.last_mutation_id = mutation
    sheet.save()
    log_activity(user=request.user,request=request,action='update',model_label='crm.LeadSheet',object_id=sheet.pk,object_repr=sheet.title,message=f'Saved sheet; {changes_count} records changed.')
    return packet(request.user, sheet)


@employee_required
@never_cache
@require_POST
def save(request):
    try:
        if len(request.body) > 3_000_000: raise SheetError('This sheet is too large. Save a smaller group of rows.')
        payload = json.loads(request.body)
        if not isinstance(payload, dict): raise ValueError()
        with transaction.atomic():
            data = persist(request, payload)
        return JsonResponse(data)
    except SheetError as exc:
        return JsonResponse({'error':exc.message,'errors':exc.errors}, status=exc.status)
    except (ValueError, TypeError, UnicodeDecodeError, RequestDataTooBig):
        return JsonResponse({'error':'The sheet could not be read. Reload and try again.'}, status=400)


@employee_required
@never_cache
@require_GET
def export(request, pk=None):
    from .sheet_files import make_xlsx, make_csv
    if pk:
        sheet = get_object_or_404(LeadSheet, pk=pk, owner=request.user)
        kind, title = sheet.kind, sheet.title
        lookup = {r.pk:r for r in scoped(request.user,kind).filter(pk__in=[r['pk'] for r in sheet.rows])}
        records = [lookup[ref['pk']] for ref in sheet.rows if ref['pk'] in lookup]
    else:
        kind, qs = selection(request)
        title = 'Lead template' if request.GET.get('source', 'blank') == 'blank' else 'Lead export'
        if qs.count() > MAX_EXPORT_ROWS:
            return HttpResponse(f'Filter to {MAX_EXPORT_ROWS:,} records or fewer before exporting.',status=400)
        records = list(qs)
    schema = columns(request.user, kind)
    rows = []
    for record in records:
        values = values_for(record, schema)
        token = signing.dumps({'user':request.user.pk,'kind':kind,'pk':record.pk,'version':version_for(record)},salt=FILE_SALT,compress=True)
        row = []
        for col in schema:
            value = values[col['key']]
            row.append(dict((str(k),v) for k,v in col['choices']).get(value, value))
        rows.append(row+[token])
    csv_format = request.GET.get('format') == 'csv'
    content = make_csv(schema, rows) if csv_format else make_xlsx(schema, rows, kind)
    response = HttpResponse(content,content_type='text/csv; charset=utf-8' if csv_format else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    from django.utils.text import slugify
    response['Content-Disposition'] = f'attachment; filename="{slugify(title) or "leads"}.{ "csv" if csv_format else "xlsx"}"'
    response['Cache-Control'] = 'private, no-store'
    log_activity(user=request.user,request=request,action='export',model_label='crm.LeadSheet',message=f'Exported {len(rows)} scoped {kind}.')
    return response


@employee_required
@never_cache
@require_POST
def import_preview(request):
    from .sheet_files import read_file
    try:
        uploaded = request.FILES.get('file')
        schema = columns(request.user)
        rows, warnings = read_file(uploaded, schema)
        sheet = LeadSheet(owner=request.user,title=(uploaded.name.rsplit('.',1)[0] or 'Imported leads')[:150])
        refs, preview = {}, []
        kind = None
        for index, values in enumerate(rows, 2):
            key = str(uuid.uuid4())
            token = values.pop('_crm_record', '')
            baseline = {}
            if token:
                try:
                    ref = signing.loads(token, salt=FILE_SALT, max_age=90*86400)
                    if ref['user'] != request.user.pk: raise signing.BadSignature()
                    if kind and kind != ref['kind']: raise signing.BadSignature()
                    kind = ref['kind']
                    record = scoped(request.user, kind).filter(pk=ref['pk']).first()
                    if not record or version_for(record) != ref['version']: raise signing.BadSignature()
                    if any(r['pk']==record.pk for r in refs.values()): raise signing.BadSignature()
                except (signing.BadSignature, KeyError):
                    raise SheetError(f'Row {index}: its linked CRM record changed, is unavailable, or was exported by another user. Download a fresh export before editing.')
                refs[key] = {'pk':record.pk,'version':ref['version']}
                baseline = values_for(record, columns(request.user, kind))
            preview.append({'key':key,'values':baseline,'changes':values})
        sheet.kind = kind or 'leads'
        data = packet(request.user, sheet)
        # Parsing aliases is shared; validation and authorization still happen on Save.
        data['rows'] = preview
        data['snapshot'] = signing.dumps({'user':request.user.pk,'sheet':str(sheet.pk),'kind':sheet.kind,'revision':0,'refs':refs},salt=SALT,compress=True)
        data['warnings'] = warnings
        return JsonResponse(data)
    except (SheetError, ValueError) as exc:
        return JsonResponse({'error':str(exc) if isinstance(exc,ValueError) else exc.message},status=400)
