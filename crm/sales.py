"""Shared sales workflow and source-grounded preparation for staff."""
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

ASSESSMENT_DESCRIPTION = (
    "A 15–20 minute video Growth Assessment with an AI Specialist. Review the business and "
    "how it operates today, identify useful AI opportunities, then propose an implementation "
    "strategy and custom pricing based on the scope."
)
BOOKING_URL = "https://calendly.com/theaibizguru/15-minute-intro-to-ai"
STAGES = [
    ("new", "New", ["new", "not_contacted"]),
    ("outreach", "Reaching out", ["attempted", "no_answer", "voicemail_left", "gatekeeper_reached", "decision_maker_unavailable", "contacted", "demo_sent"]),
    ("conversation", "In conversation", ["decision_maker_reached", "information_requested", "email_requested", "callback_requested", "follow_up", "warm_lead", "hot_lead", "corporate_referral", "existing_vendor", "already_uses_ai", "has_internal_marketing"]),
    ("assessment", "Assessment booked", ["appointment_scheduled"]),
    ("strategy", "Strategy & proposal", ["appointment_completed", "proposal_requested", "proposal_sent"]),
    ("won", "Won", ["closed_won", "client_onboarded"]),
    ("closed", "Closed / do not contact", ["not_interested", "do_not_contact", "closed_lost", "duplicate", "duplicate_review", "permanently_closed", "disconnected_number", "wrong_number"]),
]
INACTIVE = STAGES[-1][2] + STAGES[-2][2]

def stage_for(lead):
    return next(((key, label) for key, label, statuses in STAGES if lead.status in statuses), ("new", "New"))

def due_filter():
    return Q(follow_up_date__lte=timezone.localdate()) | Q(next_follow_up_at__lte=timezone.now()) | (Q(status__in=["callback_requested", "follow_up"]) & Q(follow_up_date__isnull=True) & Q(next_follow_up_at__isnull=True))

def annotate_leads(leads):
    for lead in leads:
        lead.sales_stage, lead.sales_stage_label = stage_for(lead)
        lead.contact_blocked = lead.status in INACTIVE
    return leads

def playbook(lead=None):
    industry = (lead.industry if lead else "").lower()
    if any(word in industry for word in ["restaurant", "food", "hospitality", "hotel"]):
        question = "What happens to reservation and customer questions when your team is busy?"
        angle = "Inquiry handling, reservation requests and follow-up"
    elif any(word in industry for word in ["roof", "hvac", "construction", "home", "solar", "auto"]):
        question = "How do you handle a new inquiry when everyone is on a job or away from the phone?"
        angle = "Missed-call follow-up, intake and quote requests"
    elif any(word in industry for word in ["dent", "health", "medical", "salon", "spa", "chiro"]):
        question = "Where does your front desk spend the most time on repetitive appointment questions?"
        angle = "Administrative intake, appointment requests and reminders"
    else:
        question = "Where does your team spend the most time repeating the same task or following up manually?"
        angle = "Inquiry handling, follow-up and repetitive administration"
    business = (lead.business_name or lead.name or "your business") if lead else "your business"
    return {
        "question": question, "angle": angle,
        "opener": f"Hi, I’m with AI Business Gurus. I’m learning how {business} handles day-to-day operations. {question}",
        "invitation": "Would a 15–20 minute video Growth Assessment with an AI Specialist be useful? We’ll review how your business operates, identify where AI could help, and outline an implementation strategy with custom pricing.",
        "objection": "That makes sense. This is a short business review, so we can first understand what you already have and whether there is a useful gap to address. If the timing isn’t right, we can leave it there.",
        "description": ASSESSMENT_DESCRIPTION,
    }

def guide_url(lead=None):
    url = reverse("concierge") + "?embed=1&sales=1"
    return url + f"&lead={lead.pk}" if lead else url
