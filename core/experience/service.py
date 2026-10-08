"""Fictional service intake and repair orders, contained in one demo session."""
import uuid
from django import forms
from django.utils import timezone
from .financing import clean_phone


SERVICE_TYPES = [
    ("maintenance", "Scheduled maintenance"), ("oil", "Oil & filter change"),
    ("tires", "Tires & rotation"), ("brakes", "Brake concern"),
    ("battery", "Battery check"), ("diagnostic", "Warning light / diagnostic"),
    ("other", "Other service concern"),
]
VISIT_TYPES = [("undecided", "Discuss with advisor"), ("drop_off", "Drop off"), ("wait", "Prefer to wait")]
STATUS_CHOICES = [
    ("intake", "Intake received"), ("scheduled", "Scheduled"), ("checked_in", "Checked in"),
    ("inspection", "Inspection"), ("awaiting_approval", "Awaiting customer approval"),
    ("in_progress", "Work in progress"), ("ready", "Ready for pickup"),
    ("closed", "Closed"), ("cancelled", "Cancelled"),
]
ADVISORS = [("Jordan Ellis · Service", "Jordan Ellis · Service"), ("Morgan Lee · Service", "Morgan Lee · Service")]
TECHNICIANS = [("", "Not assigned"), ("Casey Brooks", "Casey Brooks"), ("Sam Patel", "Sam Patel")]
TRANSITIONS = {
    "intake": {"scheduled", "checked_in", "cancelled"},
    "scheduled": {"checked_in", "cancelled"},
    "checked_in": {"inspection", "cancelled"},
    "inspection": {"awaiting_approval", "cancelled"},
    "awaiting_approval": {"in_progress", "cancelled"},
    "in_progress": {"ready"}, "ready": {"closed"}, "closed": set(), "cancelled": set(),
}
CUSTOMER_EDITABLE = {"intake", "scheduled"}


class DemoServiceForm(forms.Form):
    name = forms.CharField(label="Customer name", max_length=100)
    phone = forms.CharField(label="Phone (optional)", max_length=30, required=False,
                           widget=forms.TextInput(attrs={"type": "tel", "placeholder": "202-555-0146"}))
    email = forms.EmailField(label="Email (optional)", max_length=254, required=False,
                            widget=forms.EmailInput(attrs={"placeholder": "taylor@example.com"}))
    vehicle = forms.CharField(label="Year, make & model", min_length=3, max_length=120,
                             widget=forms.TextInput(attrs={"placeholder": "2021 Honda CR-V"}))
    mileage = forms.IntegerField(label="Mileage (if known)", min_value=0, max_value=1000000, required=False)
    services = forms.MultipleChoiceField(label="Requested services", choices=SERVICE_TYPES, widget=forms.CheckboxSelectMultiple)
    concern = forms.CharField(label="What should the advisor know?", min_length=3, max_length=1000,
                              widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Tell us what you noticed or the maintenance you need."}))
    visit_type = forms.ChoiceField(label="Visit preference", choices=VISIT_TYPES)
    demo_acknowledged = forms.BooleanField(label="This is a fictional intake and service order, not a real repair authorization or booking.")

    def clean_phone(self):
        value = self.cleaned_data["phone"]
        try:
            return clean_phone(value) if value else ""
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from None


class DemoServiceStaffForm(forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    status = forms.ChoiceField(label="Move order to", choices=STATUS_CHOICES)
    advisor = forms.ChoiceField(label="Service advisor", choices=ADVISORS)
    technician = forms.ChoiceField(label="Technician", choices=TECHNICIANS, required=False)
    advisor_notes = forms.CharField(label="Advisor notes / inspection findings (fictional)", max_length=2000, required=False,
                                    widget=forms.Textarea(attrs={"rows": 3}))
    approval_confirmed = forms.BooleanField(label="Simulate the customer's approval of the described work", required=False)

    def __init__(self, *args, order, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = TRANSITIONS[order["status"]] | {order["status"]}
        if not order.get("appointment_slot"):
            allowed.discard("scheduled")
        self.fields["status"].choices = [(k, v) for k, v in STATUS_CHOICES if k in allowed]


def public_order(session):
    order = session.state.get("service_order")
    if not order:
        return None
    return {**order, "status_label": dict(STATUS_CHOICES)[order["status"]],
            "service_labels": [dict(SERVICE_TYPES)[k] for k in order.get("services", [])],
            "visit_label": dict(VISIT_TYPES).get(order.get("visit_type"), "Not discussed"),
            "customer_editable": order["status"] in CUSTOMER_EDITABLE,
            "customer": session.state.get("customer", {}),
            "appointment": session.state.get("appointments", {}).get("service")}


def record_event(session, order, action, description):
    stamp = timezone.now().isoformat()
    order["version"] = order.get("version", 0) + 1
    order["updated_at"] = stamp
    order.setdefault("history", []).append({"action": action, "description": description, "at": stamp})
    order["history"] = order["history"][-40:]
    session.state.setdefault("crm_actions", []).append({"action": action, "description": description[:500]})


def update_intake(session, fields):
    order = session.state.get("service_order")
    if order and order["status"] not in CUSTOMER_EDITABLE:
        raise ValueError("This order is already with the service team. Ask the advisor to review changes; do not overwrite their work.")
    is_new = not order
    if not order:
        order = {"id": "DEMO-RO-" + uuid.uuid4().hex[:10].upper(), "status": "intake", "version": 0,
                 "services": [], "advisor": ADVISORS[0][0], "technician": "", "advisor_notes": "",
                 "approval": None, "synthetic": True, "created_at": timezone.now().isoformat()}
    updates = {k: v for k, v in fields.items() if k in ("vehicle", "mileage", "services", "concern", "visit_type") and v is not None}
    if "services" in updates:
        updates["services"] = list(dict.fromkeys(updates["services"]))
    changed = any(order.get(k) != v for k, v in updates.items())
    order.update(updates)
    session.state["service_order"] = order
    appointment = session.state.get("appointments", {}).get("service")
    if appointment:
        for source, target in (("vehicle", "vehicle_description"), ("concern", "request")):
            if source in updates:
                appointment[target] = updates[source]
    if session.state.get("stage") == "ready":
        session.state["stage"] = "discovery"
    if is_new or changed:
        record_event(session, order, "Service intake received" if is_new else "Service intake updated",
                     f"{order['id']} · Customer-stated service needs saved for the fictional service advisor.")
    return order


def attach_appointment(session, appointment):
    order = update_intake(session, {"vehicle": appointment["vehicle_description"], "concern": appointment["request"]})
    if order.get("appointment_slot") != appointment["id"] or order["status"] != "scheduled":
        order["appointment_slot"] = appointment["id"]
        order["status"] = "scheduled"
        record_event(session, order, "Service intake scheduled", f"{order['id']} · {appointment['label']} · Intake time only.")
    return order


def update_staff(session, cleaned):
    order = session.state["service_order"]
    if cleaned["version"] != order["version"]:
        raise ValueError("This service order changed. Refresh the record before saving your update.")
    old, new = order["status"], cleaned["status"]
    if new != old and new not in TRANSITIONS[old]:
        raise ValueError("Choose the next available step for this service order.")
    if new == "scheduled" and not order.get("appointment_slot"):
        raise ValueError("Choose a service appointment time through intake before marking this order scheduled.")
    if new == "in_progress" and old != new:
        if not cleaned["approval_confirmed"] or not cleaned["advisor_notes"].strip():
            raise ValueError("Describe the work and confirm simulated customer approval before starting it.")
        if not cleaned["technician"]:
            raise ValueError("Assign a technician before starting the demo work.")
        order["approval"] = {"at": timezone.now().isoformat(), "work": cleaned["advisor_notes"], "synthetic": True}
    changed = old != new or any(order.get(k, "") != cleaned[k] for k in ("advisor", "technician", "advisor_notes"))
    for key in ("status", "advisor", "technician", "advisor_notes"):
        order[key] = cleaned[key]
    if changed:
        record_event(session, order, "Service order updated", f"{order['id']} · {dict(STATUS_CHOICES)[old]} → {dict(STATUS_CHOICES)[new]} · {order['advisor']}")
    appointment = session.state.get("appointments", {}).get("service")
    if appointment and new in ("cancelled", "closed"):
        appointment["status"] = "cancelled" if new == "cancelled" else "completed"
    if new in ("cancelled", "closed") and not session.state.get("vehicles") and not session.state.get("appointments", {}).get("sales") and not session.state.get("financing_application"):
        session.state["stage"] = "closed"
    # A staff update changes the live context. Avoid stale tool exchanges implying an older order state.
    session.protocol = []
    return order
