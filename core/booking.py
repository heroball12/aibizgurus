"""Office availability and reservations. All times are stored in UTC, shown in Pacific."""
import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from uuid import UUID, uuid5, NAMESPACE_URL
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMessage, get_connection
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from crm.models import Lead, LeadActivity, AssessmentBooking
from crm.sales import INACTIVE
from .booking_models import OfficeSchedule, OfficeClosure, OfficeAppointment, OfficeBookingEmail
from .company import COMPANY

PACIFIC = ZoneInfo("America/Los_Angeles")
logger = logging.getLogger(__name__)


class BookingError(Exception):
    pass


def schedule():
    return OfficeSchedule.objects.get_or_create(pk=1, defaults={"notification_email": settings.OWNER_ALERT_EMAIL})[0]


def available_times(day, config=None, *, now=None):
    config = config or schedule()
    now = now or timezone.now()
    today = now.astimezone(PACIFIC).date()
    if not config.enabled or day.weekday() not in config.weekdays or not today <= day <= today + timedelta(days=config.horizon_days):
        return []
    start = datetime.combine(day, config.opens_at, PACIFIC)
    closing = datetime.combine(day, config.closes_at, PACIFIC)
    length = timedelta(minutes=config.duration_minutes)
    gap = timedelta(minutes=config.buffer_minutes)
    busy = list(OfficeAppointment.objects.filter(status="confirmed", starts_at__lt=closing, blocked_until__gt=start).values_list("starts_at", "blocked_until"))
    busy += list(OfficeClosure.objects.filter(starts_at__lt=closing, ends_at__gt=start).values_list("starts_at", "ends_at"))
    # Existing CRM/Calendly appointments also reserve owner time. The website cannot
    # read private external calendars; Calendly only supplies its synced bookings.
    external = set(AssessmentBooking.objects.filter(status="active", starts_at__gte=start - timedelta(hours=4), starts_at__lt=closing).values_list("starts_at", flat=True))
    external.update(Lead.objects.filter(lead_type="internal_sales", status="appointment_scheduled", appointment_at__gte=start - timedelta(hours=4), appointment_at__lt=closing).values_list("appointment_at", flat=True))
    busy += [(value, value + timedelta(minutes=30) + gap) for value in external]
    slots = []
    step = length + gap
    if step <= timedelta(0):
        return []
    while start + step <= closing:
        if start >= now + timedelta(hours=config.notice_hours) and not any(start < end and start + step > beginning for beginning, end in busy):
            slots.append(start)
        start += step
    return slots


def confirmation_token(appointment):
    return signing.dumps(str(appointment.pk), salt="office-confirmation")


def queue_emails(appointment, config, *, canceled=False):
    prefix = "canceled" if canceled else "confirmed"
    for audience, recipient in (("owner", config.notification_email), ("visitor", appointment.email)):
        OfficeBookingEmail.objects.get_or_create(appointment=appointment, kind=f"{prefix}_{audience}", defaults={"recipient": recipient})


@transaction.atomic
def reserve(request, data):
    config = OfficeSchedule.objects.select_for_update().get(pk=1)
    try:
        key = UUID(signing.loads(data["submission_token"], salt="office-submission", max_age=86400))
    except (signing.BadSignature, ValueError, TypeError):
        raise BookingError("This booking form has expired. Reload the page and choose your time again.") from None
    existing = OfficeAppointment.objects.filter(submission_key=key).first()
    if existing:
        return existing
    start = data["starts_at"].astimezone(PACIFIC)
    if not config.notification_email or start not in available_times(start.date(), config):
        raise BookingError("That time is no longer available. Please choose another time.")
    # A repeated submission from another tab must not create a second appointment.
    if OfficeAppointment.objects.filter(email__iexact=data["email"], status="confirmed", starts_at__gte=timezone.now()).exists():
        raise BookingError(f"Please call {COMPANY['phone']} to change an existing appointment or arrange another visit.")
    from crm.calendly import match_lead
    lead, rep, _ = match_lead({"email": data["email"], "tracking": {"utm_content": request.POST.get("ref", "")}})
    if lead:
        lead = Lead.objects.select_for_update().get(pk=lead.pk)
        if lead.archived or lead.status in INACTIVE or lead.status in {"appointment_completed", "proposal_requested", "proposal_sent"} or lead.appointment_at:
            raise BookingError(f"Please call {COMPANY['phone']} so we can arrange the right appointment for you.")
    from .models import ConsultationRequest
    details = {key: data[key] for key in ("name", "email", "phone", "business_name", "industry", "message")}
    consultation = ConsultationRequest.objects.create(**details, status="booked_in_person")
    if not lead:
        lead = Lead.objects.create(**{key: value for key, value in details.items() if key != "message"}, notes=data["message"], source="In-person Growth Assessment", lead_type="internal_sales", assigned_to=rep)
    previous_status = lead.status
    from .experience.access import attribute_assessment
    attribute_assessment(request, consultation, lead)
    appointment = OfficeAppointment.objects.create(**details, submission_key=key, starts_at=start, ends_at=start + timedelta(minutes=config.duration_minutes), blocked_until=start + timedelta(minutes=config.duration_minutes + config.buffer_minutes), consultation=consultation, lead=lead)
    brief = dict(lead.assessment_brief or {})
    brief.update({"office_appointment": str(appointment.pk), "meeting_format": "in_person", "location": COMPANY["address"], "meeting_url": ""})
    lead.appointment_at, lead.status, lead.assessment_brief = start, "appointment_scheduled", brief
    lead.follow_up_date = lead.next_follow_up_at = None
    lead.save(update_fields=["appointment_at", "status", "assessment_brief", "follow_up_date", "next_follow_up_at"])
    LeadActivity.objects.create(lead=lead, activity_type="status_change", raw_note=f"In-person Growth Assessment booked for {start:%B %d, %Y at %I:%M %p} Pacific. {data['message']}", inferred_status=lead.status, metadata={"provider": "office", "appointment": str(appointment.pk)})
    from audit.models import EmployeeLeadEvent
    actor = rep or lead.assigned_to
    EmployeeLeadEvent.objects.get_or_create(request_key=uuid5(NAMESPACE_URL, f"office:{appointment.pk}"), lead_key=lead.pk, defaults={"lead": lead, "actor": actor, "actor_name": (actor.get_full_name() or actor.username) if actor else "Website booking", "lead_name": lead.business_name or lead.name, "kind": "updated", "source": "office_booking", "previous_status": previous_status, "status": lead.status, "assessment_booked": True, "counts_as_call": False, "changes": {"appointment": {"before": "", "after": "In-person Growth Assessment booked"}}})
    queue_emails(appointment, config)
    return appointment


@transaction.atomic
def cancel(appointment_id):
    config = OfficeSchedule.objects.select_for_update().get(pk=1)
    appointment = OfficeAppointment.objects.select_for_update().get(pk=appointment_id)
    if appointment.status == "canceled":
        return appointment
    appointment.status, appointment.canceled_at = "canceled", timezone.now()
    appointment.save(update_fields=["status", "canceled_at"])
    if appointment.lead_id:
        lead = Lead.objects.select_for_update().get(pk=appointment.lead_id)
        brief = dict(lead.assessment_brief or {})
        if brief.get("office_appointment") == str(appointment.pk) and lead.status == "appointment_scheduled" and lead.appointment_at == appointment.starts_at:
            for key in ("office_appointment", "meeting_format", "location"):
                brief.pop(key, None)
            lead.appointment_at, lead.status, lead.assessment_brief = None, "follow_up", brief
            lead.next_follow_up_at = timezone.now()
            lead.save(update_fields=["appointment_at", "status", "assessment_brief", "next_follow_up_at"])
        LeadActivity.objects.create(lead=lead, activity_type="status_change", raw_note="Owner canceled the in-person Growth Assessment.", inferred_status=lead.status, metadata={"provider": "office"})
    if appointment.consultation_id:
        type(appointment.consultation).objects.filter(pk=appointment.consultation_id).update(status="canceled")
    queue_emails(appointment, config, canceled=True)
    return appointment


def ics(appointment):
    def escape(value):
        return str(value).replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")
    def utc(value):
        return value.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AI Business Gurus//Office Bookings//EN", "METHOD:PUBLISH", "BEGIN:VEVENT", f"UID:{appointment.pk}@aibiz.guru", f"DTSTAMP:{utc(appointment.created_at)}", f"DTSTART:{utc(appointment.starts_at)}", f"DTEND:{utc(appointment.ends_at)}", "SUMMARY:In-person Growth Assessment — AI Business Gurus", "LOCATION:" + escape(COMPANY["address"]), "DESCRIPTION:" + escape(f"Meet an AI Specialist at our Temecula office. Questions or changes: {COMPANY['phone']}"), "STATUS:" + ("CANCELLED" if appointment.status == "canceled" else "CONFIRMED"), "SEQUENCE:" + ("1" if appointment.status == "canceled" else "0"), "END:VEVENT", "END:VCALENDAR"]
    # RFC 5545 folding uses octets, not characters; never split a UTF-8 character.
    folded = []
    for line in lines:
        current = ""
        for char in line:
            if len((current + char).encode()) > 74:
                folded.append(current)
                current = " "
            current += char
        folded.append(current)
    return "\r\n".join(folded) + "\r\n"


def email_ready():
    return settings.EMAIL_BACKEND not in {"django.core.mail.backends.console.EmailBackend", "django.core.mail.backends.dummy.EmailBackend", "django.core.mail.backends.filebased.EmailBackend"}


def deliver_emails(appointment_id=None, *, limit=20):
    """Serialize each send, retain failures, never roll back the confirmed booking."""
    query = OfficeBookingEmail.objects.filter(delivered_at__isnull=True).exclude(
        appointment__status="canceled", kind__startswith="confirmed"
    )
    if appointment_id:
        query = query.filter(appointment_id=appointment_id)
    ids = list(query.order_by("pk").values_list("pk", flat=True)[:limit])
    for pk in ids:
        with transaction.atomic():
            item = OfficeBookingEmail.objects.select_for_update().get(pk=pk)
            if item.delivered_at:
                continue
            appointment = item.appointment
            # Do not send a stale confirmation after the owner has canceled it.
            if appointment.status == "canceled" and item.kind.startswith("confirmed"):
                continue
            item.attempts += 1
            try:
                if not email_ready() or not item.recipient:
                    raise BookingError("Configure a delivery email backend and owner email to send booking notifications.")
                when = appointment.starts_at.astimezone(PACIFIC).strftime("%A, %B %d at %I:%M %p %Z")
                status = "canceled" if appointment.status == "canceled" else "confirmed"
                body = f"Your in-person Growth Assessment is {status}.\n\n{when}\n{COMPANY['address']}\n\nName: {appointment.name}\nBusiness: {appointment.business_name}\nPhone: {appointment.phone}\nEmail: {appointment.email}\nIndustry: {appointment.industry}\n\n{appointment.message}\n\nQuestions or changes: {COMPANY['phone']}"
                if item.kind.endswith("owner"):
                    body += "\n\nOwner calendar: " + settings.PUBLIC_BASE_URL + reverse("office_calendar")
                subject = f"In-person Growth Assessment {status} · {when}"
                connection = get_connection(timeout=5)
                message = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [item.recipient], connection=connection)
                message.attach("growth-assessment.ics", ics(appointment), "text/calendar")
                if message.send(fail_silently=False) != 1:
                    raise BookingError("The mail provider did not accept the notification. Retry delivery.")
                item.delivered_at, item.last_error = timezone.now(), ""
            except BookingError as exc:
                item.last_error = str(exc)
            except Exception:
                # Provider exception messages can contain credentials or customer data.
                item.last_error = "Email delivery failed. Check server mail settings and retry."
                logger.warning("Office booking email delivery failed for notification %s", item.pk)
            item.save(update_fields=["attempts", "delivered_at", "last_error"])
