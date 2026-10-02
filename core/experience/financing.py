"""A session-only financing demonstration: no lenders, credit checks or decisions."""
import re
import uuid
from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone


FINANCING_CHOICES = [
    ("undecided", "Still exploring"),
    ("dealer_financing", "Explore dealership financing"),
    ("own_financing", "Use my own bank / credit union"),
    ("cash", "Pay in full"),
]
SAMPLE_PROFILES = {
    "employed": {"label": "Employed · sample individual", "applicant_type": "Individual", "employer": "Example Design Studio", "annual_income": 72000, "monthly_housing": 1500, "employment_months": 36},
    "self_employed": {"label": "Self-employed · sample individual", "applicant_type": "Individual", "employer": "Demo Creative Co.", "annual_income": 90000, "monthly_housing": 2000, "employment_months": 48},
    "business": {"label": "Business · sample company", "applicant_type": "Business", "employer": "Example Field Services LLC", "annual_income": 240000, "monthly_housing": 3000, "employment_months": 60},
}


def clean_phone(value):
    value = value.strip()
    if not re.fullmatch(r"\+?[0-9 ()\.\-]{7,30}", value) or not 7 <= len(re.sub(r"\D", "", value)) <= 15:
        raise ValueError("Enter a phone number with 7–15 digits, such as 202-555-0146.")
    return value


def clean_email(value):
    value = value.strip()
    try:
        validate_email(value)
    except ValidationError:
        raise ValueError("Enter a valid email, such as taylor@example.com.") from None
    return value


class DemoFinanceForm(forms.Form):
    name = forms.CharField(label="Applicant name", max_length=100, widget=forms.TextInput(attrs={"placeholder": "Taylor Demo", "autocomplete": "off"}))
    phone = forms.CharField(label="Phone", max_length=30, widget=forms.TextInput(attrs={"type": "tel", "placeholder": "202-555-0146", "autocomplete": "off"}))
    email = forms.EmailField(label="Email", max_length=254, widget=forms.EmailInput(attrs={"placeholder": "taylor@example.com", "autocomplete": "off"}))
    financing_preference = forms.ChoiceField(label="How would you like to purchase?", choices=FINANCING_CHOICES)
    stock = forms.ChoiceField(label="Vehicle", required=False)
    sample_profile = forms.ChoiceField(label="Fictional financial profile", choices=[(key, data["label"]) for key, data in SAMPLE_PROFILES.items()])
    down_payment = forms.ChoiceField(label="Sample down payment", choices=[("0", "$0"), ("2500", "$2,500"), ("5000", "$5,000"), ("10000", "$10,000")])
    term_months = forms.ChoiceField(label="Requested term (demo only)", choices=[("undecided", "Discuss with the finance team"), ("36", "36 months"), ("48", "48 months"), ("60", "60 months"), ("72", "72 months")])
    demo_acknowledged = forms.BooleanField(label="I understand this submits a fictional application only. No credit check, lender submission or financing decision will occur.")

    def __init__(self, *args, content, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stock"].choices = [("", "Still choosing a vehicle")] + [
            (v["stock"], f"{v['year']} {v['make']} {v['model']} · {v['stock']}")
            for v in content["inventory"] if v["status"] == "available"
        ]

    def clean_phone(self):
        try:
            return clean_phone(self.cleaned_data["phone"])
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from None


def open_application(session, stock=None):
    from .tools import get_vehicle
    current = session.state.get("financing_application")
    if current and current["status"] == "submitted":
        current["open_request"] = uuid.uuid4().hex
        return current
    if stock:
        vehicle = get_vehicle(session.revision.content, stock)
        if vehicle["status"] != "available":
            raise ValueError("Choose an available demo vehicle, or leave the vehicle undecided.")
    else:
        vehicle = session.state.get("appointments", {}).get("sales", {}).get("vehicle")
    application = current or {"id": "DEMO-FIN-" + uuid.uuid4().hex[:10].upper(), "status": "draft", "synthetic": True}
    application["open_request"] = uuid.uuid4().hex
    if vehicle:
        application["stock"] = vehicle["stock"]
        application["vehicle"] = vehicle
    session.state["financing_application"] = application
    if session.state.get("stage") == "ready":
        session.state["stage"] = "discovery"
    if not current:
        session.state.setdefault("crm_actions", []).append({"action": "Demo financing application opened", "description": "A fictional application is ready for customer review. No credit inquiry or lender connection."})
    return application


def submit_application(session, cleaned):
    from .tools import get_vehicle
    current = session.state["financing_application"]
    if current["status"] == "submitted":
        return current
    contact = {key: cleaned[key] for key in ("name", "phone", "email", "financing_preference")}
    session.state["customer"].update(contact)
    vehicle = get_vehicle(session.revision.content, cleaned["stock"]) if cleaned["stock"] else None
    if vehicle:
        if not session.state["customer"].get("interest"):
            session.state["customer"]["interest"] = f"{vehicle['year']} {vehicle['make']} {vehicle['model']}"
        session.state["vehicles"] = list(dict.fromkeys(session.state.get("vehicles", []) + [vehicle["stock"]]))[-18:]
    application = dict(current, status="submitted", contact=contact,
        stock=cleaned["stock"], vehicle=vehicle, sample_profile=cleaned["sample_profile"],
        financial_sample=SAMPLE_PROFILES[cleaned["sample_profile"]], down_payment=int(cleaned["down_payment"]),
        term_months=cleaned["term_months"], submitted_at=timezone.now().isoformat(),
        assigned_to="Alex Morgan · Finance", decision="Not evaluated — demonstration only")
    session.state["financing_application"] = application
    if session.state.get("stage") in ("ready", "discovery"):
        session.state["stage"] = "qualified"
    if session.state.get("stage") != "closed":
        if session.state.get("temperature") in ("new", "exploring"):
            session.state["temperature"] = "qualified"
        finance_follow_up = f"Demo finance team: review application {application['id']}. No credit check or approval."
        session.state["follow_up"] = " ".join(filter(None, [session.state.get("follow_up", ""), finance_follow_up]))
    session.state.setdefault("crm_actions", []).append({"action": "Demo financing application submitted", "description": f"{application['id']} · Queued for the fictional finance team. No credit check or lending decision."})
    return application
