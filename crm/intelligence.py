import re
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Optional
from urllib.parse import urlparse

from django.utils import timezone


BUSINESS_SUFFIX_RE = re.compile(
    r"\b(llc|inc|incorporated|co|company|corp|corporation|ltd|limited|pllc|group|services?)\b\.?",
    re.IGNORECASE,
)


@dataclass
class LeadClassification:
    status: str = "new"
    temperature: str = "cold"
    cleaned_note: str = ""
    confidence: Decimal = Decimal("0.50")
    source: str = "rule"
    contact_person: str = ""
    contact_role: str = ""
    requested_action: str = ""
    follow_up_date: Optional[object] = None
    needs_review: bool = True
    labels: list[str] = field(default_factory=list)


def normalize_phone(value):
    digits = re.sub(r"\D+", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def normalize_business_name(value):
    text = (value or "").lower()
    text = BUSINESS_SUFFIX_RE.sub("", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_domain(value):
    if not value:
        return ""
    value = value.strip().lower()
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    domain = (parsed.netloc or parsed.path).lower()
    domain = domain.removeprefix("www.")
    return domain.strip("/")


def duplicate_fingerprint(*, business_name="", phone="", website="", email="", address=""):
    parts = [
        normalize_business_name(business_name),
        normalize_phone(phone),
        normalize_domain(website),
        (email or "").strip().lower(),
        re.sub(r"[^a-z0-9]+", " ", (address or "").lower()).strip(),
    ]
    return "|".join([part for part in parts if part])


def _contains(text, *phrases):
    return any(phrase in text for phrase in phrases)


def _title_role(text):
    if "owner" in text:
        return "Owner"
    if "manager" in text or "gm" in text:
        return "Manager"
    if "corporate" in text or "headquarters" in text or "hq" in text:
        return "Corporate"
    if "receptionist" in text or "front desk" in text:
        return "Front Desk"
    if "gatekeeper" in text:
        return "Gatekeeper"
    return ""


def _extract_follow_up_date(text):
    today = timezone.localdate()
    if "tomorrow" in text:
        return today + timedelta(days=1)
    if "today" in text:
        return today
    if "next week" in text:
        return today + timedelta(days=7)
    if "this week" in text:
        return today + timedelta(days=3)
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", text)
    if match:
        month, day, year = match.groups()
        year = int(year) if year else today.year
        if year < 100:
            year += 2000
        try:
            return today.replace(year=year, month=int(month), day=int(day))
        except ValueError:
            return None
    return None


def classify_sales_note(raw_note, imported_status=""):
    original = (raw_note or "").strip()
    text = original.lower()
    if not text:
        status = imported_status or "not_contacted"
        return LeadClassification(
            status=status,
            temperature="cold",
            cleaned_note="No call notes were provided.",
            confidence=Decimal("0.42"),
            needs_review=True,
            labels=["missing_note"],
        )

    status = "attempted"
    temperature = "cold"
    confidence = Decimal("0.62")
    action = "Review and determine the next outreach step."
    labels = []
    role = _title_role(text)

    if _contains(text, "not interested", "no interest", "don’t call", "do not call", "remove me"):
        status, temperature, confidence = "not_interested", "closed", Decimal("0.95")
        action = "Do not continue active outreach unless a manager reopens the lead."
        labels.append("negative")
    elif _contains(text, "wrong number", "bad number"):
        status, temperature, confidence = "wrong_number", "closed", Decimal("0.94")
        action = "Find a corrected phone number before calling again."
        labels.append("bad_number")
    elif _contains(text, "disconnected", "number disconnected", "not in service"):
        status, temperature, confidence = "disconnected_number", "closed", Decimal("0.94")
        action = "Research a new phone number before outreach."
        labels.append("bad_number")
    elif _contains(text, "closed down", "permanently closed", "out of business"):
        status, temperature, confidence = "permanently_closed", "closed", Decimal("0.94")
        action = "Archive unless there is evidence of a new location."
        labels.append("closed_business")
    elif _contains(text, "same company", "duplicate", "dupe"):
        status, temperature, confidence = "duplicate_review", "cold", Decimal("0.88")
        action = "Review for duplicate or additional-location handling."
        labels.append("duplicate")
    elif _contains(text, "appointment", "meeting booked", "calendar", "scheduled"):
        status, temperature, confidence = "appointment_scheduled", "hot", Decimal("0.92")
        action = "Prepare for the appointment and confirm details."
        labels.append("appointment")
    elif _contains(text, "proposal", "pricing", "price sheet", "quote"):
        status, temperature, confidence = "proposal_requested", "hot", Decimal("0.88")
        action = "Prepare pricing or proposal follow-up."
        labels.append("proposal")
    elif _contains(text, "call back", "callback", "call after", "after 4", "after four", "later today"):
        status, temperature, confidence = "callback_requested", "warm", Decimal("0.90")
        action = "Call back at the requested time."
        labels.append("callback")
    elif _contains(text, "send email", "leave an email", "leave email", "email info", "asked for email", "told me to email", "gave gm email"):
        status, temperature, confidence = "email_requested", "warm", Decimal("0.90")
        action = "Send a concise follow-up email and schedule a call-back."
        labels.append("email_requested")
    elif _contains(text, "more information", "requested info", "took down info", "send information"):
        status, temperature, confidence = "information_requested", "warm", Decimal("0.86")
        action = "Send relevant information and follow up."
        labels.append("information_requested")
    elif _contains(text, "corporate", "headquarters", "hq"):
        status, temperature, confidence = "corporate_referral", "warm", Decimal("0.84")
        action = "Identify and contact the corporate decision-making team."
        labels.append("corporate")
    elif _contains(text, "already have marketing", "has marketing", "internal marketing", "marketing team"):
        status, temperature, confidence = "has_internal_marketing", "cold", Decimal("0.82")
        action = "Position AI as missed-call, follow-up, or operations support rather than generic marketing."
        labels.append("marketing_objection")
    elif _contains(text, "already have vendor", "existing vendor", "using another company"):
        status, temperature, confidence = "existing_vendor", "cold", Decimal("0.82")
        action = "Log the existing-vendor objection and consider a later nurture touch."
        labels.append("existing_vendor")
    elif _contains(text, "already uses ai", "using ai", "have ai"):
        status, temperature, confidence = "already_uses_ai", "cold", Decimal("0.80")
        action = "Ask what AI is currently doing and look for gaps before pitching."
        labels.append("existing_ai")
    elif _contains(text, "decision maker", "spoke with owner", "owner answered", "manager handles", "manager is"):
        status, temperature, confidence = "decision_maker_reached", "warm", Decimal("0.78")
        action = "Follow up with a specific AI use case and next step."
        labels.append("decision_maker")
        role = role or "Decision Maker"
    elif _contains(text, "owner not there", "owner unavailable", "manager not there", "dm not there"):
        status, temperature, confidence = "decision_maker_unavailable", "cold", Decimal("0.86")
        action = "Call again when the decision maker is available."
        labels.append("decision_maker_unavailable")
    elif _contains(text, "gatekeeper", "wouldn't transfer", "would not transfer", "front desk"):
        status, temperature, confidence = "gatekeeper_reached", "cold", Decimal("0.82")
        action = "Use a sharper opener or ask for the best time to reach the owner/manager."
        labels.append("gatekeeper")
        role = role or "Gatekeeper"
    elif _contains(text, "voicemail", "left vm", "left a message"):
        status, temperature, confidence = "voicemail_left", "cold", Decimal("0.88")
        action = "Try a second call and optional follow-up email/text if available."
        labels.append("voicemail")
    elif _contains(text, "no answer", "na", "didn't answer", "did not answer", "answered but nobody talked"):
        status, temperature, confidence = "no_answer", "cold", Decimal("0.80")
        action = "Attempt again at a different time."
        labels.append("no_answer")

    follow_up = _extract_follow_up_date(text)
    if follow_up and temperature != "closed":
        labels.append("follow_up_date")
        if status in {"attempted", "no_answer"}:
            status = "follow_up"
            temperature = "warm"
        confidence = max(confidence, Decimal("0.78"))

    cleaned = build_clean_note(original, status, action, role, follow_up)
    needs_review = confidence < Decimal("0.72") or status in {"duplicate_review", "attempted"}
    return LeadClassification(
        status=status,
        temperature=temperature,
        cleaned_note=cleaned,
        confidence=confidence,
        source="rule",
        contact_role=role,
        requested_action=action,
        follow_up_date=follow_up,
        needs_review=needs_review,
        labels=labels,
    )


def build_clean_note(original, status, action, role="", follow_up=None):
    status_text = status.replace("_", " ")
    sentences = [f"Original SDR note indicates: {original}"]
    if role:
        sentences.append(f"The relevant contact role appears to be {role}.")
    sentences.append(f"Standardized outcome: {status_text.title()}.")
    if follow_up:
        sentences.append(f"Suggested follow-up date: {follow_up:%Y-%m-%d}.")
    sentences.append(f"Recommended next step: {action}")
    return " ".join(sentences)


def draft_follow_up_email(lead):
    business = lead.business_name or "your business"
    contact = lead.point_of_contact or lead.name or "there"
    service_angle = "AI receptionist and follow-up automation"
    if lead.industry:
        service_angle = f"AI receptionist and follow-up automation for {lead.industry}"

    if lead.status == "email_requested":
        opener = "Thanks for taking a moment on the phone today."
        next_step = "I wanted to send a quick overview like requested and see whether it makes sense to map out where leads may be slipping through."
    elif lead.status == "callback_requested":
        opener = "Thanks for asking me to follow back up."
        next_step = "I can keep this brief: the goal is to help your team answer faster, capture more serious inquiries, and reduce manual follow-up."
    elif lead.status in {"proposal_requested", "appointment_scheduled", "hot_lead"}:
        opener = "Great speaking with you."
        next_step = "Based on what we discussed, I think there may be a practical opportunity to use AI to recover missed calls, qualify leads, and support your team."
    else:
        opener = "I’m reaching out from AI Business Gurus."
        next_step = "We help businesses use AI employees to answer questions, capture leads, and follow up faster without adding more front-desk workload."

    return (
        f"Subject: Quick AI follow-up for {business}\n\n"
        f"Hi {contact},\n\n"
        f"{opener} {next_step}\n\n"
        f"For {business}, the most relevant starting point may be {service_angle}.\n\n"
        "Would it be worth taking 15 minutes to look at where an AI employee could save time or recover more opportunities?\n\n"
        "Best,\n"
        "AI Business Gurus"
    )


def csv_safe(value):
    text = str(value or "")
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text
