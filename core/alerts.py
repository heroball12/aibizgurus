import logging
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

def notify_lead_created(lead):
    subject = f"New lead: {lead.name or lead.business_name or 'Unknown'}"
    body = (
        f"Lead type: {lead.lead_type}\n"
        f"Business: {lead.business_name}\n"
        f"Client: {lead.client}\n"
        f"Industry: {lead.industry}\n"
        f"Phone: {lead.phone}\n"
        f"Email: {lead.email}\n"
        f"Source: {lead.source}\n"
        f"Status: {lead.status}\n\n"
        f"Notes:\n{lead.notes}"
    )
    if lead.lead_type == "client_customer" and lead.client and not lead.client.is_paid_active:
        logger.info("Demo lead captured without production alert: %s", body)
        return False

    recipients = []
    if settings.OWNER_ALERT_EMAIL:
        recipients.append(settings.OWNER_ALERT_EMAIL)
    if lead.client and lead.client.contact_email:
        recipients.append(lead.client.contact_email)
    recipients = list(dict.fromkeys([x for x in recipients if x]))
    if not recipients:
        logger.info("Lead alert: %s", body)
        return False
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=True)
        return True
    except Exception:
        logger.exception("Lead alert failed")
        return False
