"""Shared, explicit column contract for the CRM editor and file round trips."""
import hashlib
import json
from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from .models import Lead, LeadStaging
from .views import is_sales_manager

MAX_ROWS = 500
MAX_EXPORT_ROWS = 10000
BRIEF_FIELDS = ('workflow', 'tools', 'bottleneck', 'goal', 'strategy', 'pricing')


def columns(user, kind='leads'):
    model = LeadStaging if kind == 'prospects' else Lead
    groups = [
        ('Contact', [('business_name', 'Business name'), ('industry', 'Industry'), ('phone', 'Phone'), ('website', 'Website'), ('city', 'City'), ('state', 'State')]),
        ('Outreach', [('status', 'Status'), ('notes', 'Notes')]),
        ('Details', [('address', 'Street address')]),
    ]
    if kind == 'leads':
        groups[0][1][2:2] = [('name', 'Contact name'), ('email', 'Email')]
        groups[1][1][1:1] = [('lead_temperature', 'Temperature'), ('follow_up_date', 'Follow-up date'), ('source', 'Source')]
        groups[2][1].extend([('zip_code', 'ZIP / postal code'), ('point_of_contact', 'Decision maker'), ('contact_role', 'Contact role'), ('value', 'Opportunity value'), ('cleaned_notes', 'Summary notes')])
        if is_sales_manager(user):
            groups[1][1].append(('assigned_to', 'Assigned to'))
        groups.append(('Assessment', list(zip(BRIEF_FIELDS, ['Current workflow', 'Current tools', 'Main bottleneck', 'Business goal', 'AI strategy', 'Pricing notes']))))
    else:
        groups[2][1].append(('source_url', 'Source URL'))
    result = []
    for group, fields in groups:
        for key, label in fields:
            actual = 'phone_number' if kind == 'prospects' and key == 'phone' else key
            field = None if key in BRIEF_FIELDS else model._meta.get_field(actual)
            choices = list(field.choices or []) if field else []
            if key == 'assigned_to':
                staff = get_user_model().objects.filter(is_active=True).filter(
                    Q(role__in=['employee', 'admin', 'owner']) | Q(is_staff=True)
                ).order_by('username')
                choices = [('', 'Unassigned')] + [(str(u.pk), u.username) for u in staff]
            kind_type = 'select' if choices else 'date' if key == 'follow_up_date' else 'number' if key == 'value' else 'textarea' if key in (*BRIEF_FIELDS, 'notes', 'cleaned_notes') else 'text'
            result.append({'key': key, 'field': actual, 'label': label, 'group': group, 'type': kind_type, 'choices': choices, 'maxLength': (field.max_length if field else 4000) or 10000})
    return result


def values_for(record, schema):
    result = {}
    for col in schema:
        key = col['key']
        if key in BRIEF_FIELDS:
            value = (record.assessment_brief or {}).get(key, '')
        elif key == 'assigned_to':
            value = record.assigned_to_id
        else:
            value = getattr(record, col['field'])
        result[key] = '' if value is None else str(value)
    return result


def version_for(record):
    # Include every concrete field: form edits, reassignment and deletion must be noticed.
    data = {f.attname: getattr(record, f.attname) for f in record._meta.concrete_fields}
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()


def clean_changes(changes, schema):
    allowed = {c['key']: c for c in schema}
    errors, cleaned = {}, {}
    for key, value in changes.items():
        if key not in allowed:
            errors[key] = 'This column cannot be edited.'
            continue
        col = allowed[key]
        if not isinstance(value, str):
            errors[key] = 'Enter text or a number in this cell.'
            continue
        if len(value) > col['maxLength']:
            errors[key] = f"Use at most {col['maxLength']} characters."
            continue
        if col['type'] == 'select':
            labels = {label.casefold(): str(code) for code, label in col['choices']}
            value = labels.get(value.strip().casefold(), value.strip())
            field = forms.ChoiceField(choices=col['choices'], required=key != 'assigned_to')
        elif col['type'] == 'date':
            field = forms.DateField(required=False, input_formats=['%Y-%m-%d', '%m/%d/%Y'])
        elif key == 'value':
            field = forms.DecimalField(required=False, max_digits=10, decimal_places=2, min_value=0)
        elif key == 'email':
            field = forms.EmailField(required=False)
        elif key in ('website', 'source_url'):
            field = forms.URLField(required=False, assume_scheme='https')
        else:
            field = forms.CharField(required=False, max_length=col['maxLength'])
        try:
            cleaned[key] = field.clean(value)
            if key in ('website', 'source_url') and cleaned[key]:
                from urllib.parse import urlsplit
                parsed = urlsplit(cleaned[key])
                if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
                    raise forms.ValidationError('Enter an http or https website without a username or password.')
            if key == 'value' and cleaned[key] is None:
                cleaned[key] = 0
        except forms.ValidationError as exc:
            errors[key] = ' '.join(exc.messages)
    return cleaned, errors
