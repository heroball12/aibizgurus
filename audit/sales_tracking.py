"""Track human CRM edits once per lead per request, independently of audit messages."""
import json
import uuid
from datetime import datetime, timezone as dt_timezone

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver

from crm.models import Lead, LeadNote, LeadActivity
from .models import EmployeeLeadEvent
from .threadlocal import get_current_request

# Imports, background jobs, website research and outreach never become calls.
MANUAL_SOURCES = {
    "lead_edit", "lead_detail", "lead_progress", "lead_bulk_action", "lead_sheet_save",
    "crm_lead_change", "crm_leadnote_add", "crm_leadnote_change",
}
IGNORED_FIELDS = {"id", "created_at", "website_review", "business_verification", "duplicate_key"}


def context():
    request = get_current_request()
    user = getattr(request, "user", None)
    if not request or request.method not in {"POST", "PUT", "PATCH", "DELETE"} or not user or not user.is_authenticated or not user.is_employee_or_admin():
        return None
    source = getattr(getattr(request, "resolver_match", None), "url_name", "") or ""
    return request, user, source


def snapshot(lead):
    values = {f.attname: getattr(lead, f.attname) for f in lead._meta.concrete_fields if f.name not in IGNORED_FIELDS}
    for key, value in values.items():
        if isinstance(value, datetime) and value.tzinfo is not None:
            values[key] = value.astimezone(dt_timezone.utc)
    return json.loads(json.dumps(values, cls=DjangoJSONEncoder))


def record(lead, kind, before=None, *, note=False, call=False):
    ctx = context()
    if not ctx or lead.lead_type != "internal_sales":
        return
    request, actor, source = ctx
    after = snapshot(lead)
    changes = {key: {"before": (before or {}).get(key), "after": value} for key, value in after.items() if value != (before or {}).get(key)}
    if note:
        changes = {"note": {"before": "", "after": "Lead note saved"}}
    if kind == "updated" and not changes and not call:
        return
    if not hasattr(request, "sales_event_key"):
        request.sales_event_key = uuid.uuid4()
    event, _ = EmployeeLeadEvent.objects.get_or_create(
        request_key=request.sales_event_key, lead_key=lead.pk,
        defaults={"actor": actor, "actor_name": (actor.get_full_name() or actor.username)[:150], "lead": None if kind == "deleted" else lead, "lead_name": lead.business_name or lead.name or str(lead.pk), "kind": kind, "source": source, "previous_status": (before or {}).get("status", "")},
    )
    # A lead creation with an initial note is still one creation, never a call.
    merged = dict(event.changes)
    for key, value in changes.items():
        merged[key] = {"before": merged.get(key, value)["before"], "after": value["after"]}
    event.changes = merged
    event.status = lead.status
    event.counts_as_call = event.counts_as_call or call or (event.kind == "updated" and source in MANUAL_SOURCES)
    prior = event.previous_status
    manual = source in MANUAL_SOURCES or source in {"lead_create", "crm_lead_add"}
    if manual:
        event.assessment_booked = bool(lead.appointment_at and lead.status in {"appointment_scheduled", "appointment_completed"} and (prior not in {"appointment_scheduled", "appointment_completed"} or not (before or {}).get("appointment_at"))) or event.assessment_booked
        event.assessment_completed = event.assessment_completed or (lead.status == "appointment_completed" and prior != lead.status)
        event.proposal = event.proposal or (lead.status in {"proposal_requested", "proposal_sent"} and prior not in {"proposal_requested", "proposal_sent"})
        event.won = event.won or (lead.status in {"closed_won", "client_onboarded"} and prior not in {"closed_won", "client_onboarded"})
        event.lost = event.lost or (lead.status == "closed_lost" and prior != lead.status)
    if kind == "deleted":
        event.kind = "deleted"
        event.lead = None
    event.save()


@receiver(pre_save, sender=Lead)
def before_lead_save(sender, instance, raw=False, **kwargs):
    if not raw and context() and instance.pk:
        previous = Lead.objects.filter(pk=instance.pk).first()
        instance._sales_before = snapshot(previous) if previous else None


@receiver(post_save, sender=Lead)
def after_lead_save(sender, instance, created, raw=False, update_fields=None, **kwargs):
    if raw or not context():
        return
    # Read back actual persisted fields; save(update_fields=...) may leave unsaved values on the instance.
    persisted = Lead.objects.get(pk=instance.pk) if update_fields else instance
    record(persisted, "created" if created else "updated", getattr(instance, "_sales_before", None))


@receiver(post_save, sender=LeadNote)
def lead_note_saved(sender, instance, raw=False, **kwargs):
    if not raw and context():
        record(instance.lead, "updated", snapshot(instance.lead), note=True)


@receiver(post_delete, sender=Lead)
def lead_deleted(sender, instance, **kwargs):
    record(instance, "deleted", snapshot(instance))


@receiver(post_save, sender=LeadActivity)
def explicit_call_saved(sender, instance, created, raw=False, **kwargs):
    ctx = context()
    if not raw and created and ctx and instance.activity_type == "call" and not instance.original_import_id and instance.user_id == ctx[1].pk:
        record(instance.lead, "updated", snapshot(instance.lead), call=True)
    elif not raw and created and ctx and ctx[2] == "lead_progress" and ctx[0].POST.get("outcome-note", "").strip():
        record(instance.lead, "updated", snapshot(instance.lead), note=True)
