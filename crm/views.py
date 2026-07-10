import csv
import io
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from .models import Lead
from .forms import LeadCSVUploadForm, LeadForm, LeadNoteForm


User = get_user_model()

CSV_ALIASES = {
    "name": ["name", "contact_name", "full_name", "person"],
    "business_name": ["business_name", "business", "company", "company_name", "organization"],
    "industry": ["industry", "category"],
    "phone": ["phone", "phone_number", "mobile", "cell"],
    "email": ["email", "email_address"],
    "source": ["source", "lead_source"],
    "status": ["status", "stage"],
    "notes": ["notes", "note", "comments", "description"],
    "value": ["value", "deal_value", "estimated_value"],
    "assigned_to": ["assigned_to", "assigned", "owner", "user"],
    "follow_up_date": ["follow_up_date", "followup_date", "follow_up", "next_follow_up"],
}

STATUS_VALUES = {choice[0] for choice in Lead.STATUS_CHOICES}
STATUS_LABELS = {
    label.lower().replace("-", "_").replace(" ", "_"): value
    for value, label in Lead.STATUS_CHOICES
}


def _csv_key(value):
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _csv_value(row, field):
    for alias in CSV_ALIASES[field]:
        value = row.get(alias)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _parse_decimal(value, row_number, errors):
    if not value:
        return Decimal("0")
    cleaned = value.replace("$", "").replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        errors.append(f"Row {row_number}: value must be a number.")
        return Decimal("0")


def _parse_status(value, row_number, errors):
    if not value:
        return "new"
    normalized = _csv_key(value)
    if normalized in STATUS_VALUES:
        return normalized
    if normalized in STATUS_LABELS:
        return STATUS_LABELS[normalized]
    errors.append(f"Row {row_number}: status '{value}' is not valid.")
    return "new"


def _parse_follow_up_date(value, row_number, errors):
    if not value:
        return None
    parsed = parse_date(value)
    if not parsed:
        errors.append(f"Row {row_number}: follow_up_date must be YYYY-MM-DD.")
    return parsed


def _parse_assigned_to(value, row_number, errors):
    if not value:
        return None
    user = User.objects.filter(username=value).first() or User.objects.filter(email=value).first()
    if not user:
        errors.append(f"Row {row_number}: assigned_to user '{value}' was not found.")
    return user


def parse_internal_lead_csv(uploaded_file):
    try:
        text = uploaded_file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], ["CSV must be UTF-8 encoded."]

    try:
        reader = csv.DictReader(io.StringIO(text))
    except csv.Error as exc:
        return [], [f"CSV could not be read: {exc}"]

    if not reader.fieldnames:
        return [], ["CSV must include a header row."]

    normalized_headers = [_csv_key(header) for header in reader.fieldnames]
    rows = []
    errors = []

    for row_number, raw_row in enumerate(reader, start=2):
        if row_number > 1001:
            errors.append("CSV import is limited to 1,000 rows at a time.")
            break

        row = {
            _csv_key(key): str(value or "").strip()
            for key, value in raw_row.items()
            if key is not None
        }
        if not any(row.values()):
            continue

        name = _csv_value(row, "name")
        business_name = _csv_value(row, "business_name")
        email = _csv_value(row, "email")
        phone = _csv_value(row, "phone")

        if not any([name, business_name, email, phone]):
            errors.append(f"Row {row_number}: include at least one of name, business_name, email, or phone.")

        if email:
            try:
                validate_email(email)
            except ValidationError:
                errors.append(f"Row {row_number}: email '{email}' is not valid.")

        rows.append({
            "lead_type": "internal_sales",
            "client": None,
            "ai_instance": None,
            "name": name,
            "business_name": business_name,
            "industry": _csv_value(row, "industry"),
            "phone": phone,
            "email": email,
            "source": _csv_value(row, "source") or "CSV Upload",
            "status": _parse_status(_csv_value(row, "status"), row_number, errors),
            "notes": _csv_value(row, "notes"),
            "value": _parse_decimal(_csv_value(row, "value"), row_number, errors),
            "assigned_to": _parse_assigned_to(_csv_value(row, "assigned_to"), row_number, errors),
            "follow_up_date": _parse_follow_up_date(_csv_value(row, "follow_up_date"), row_number, errors),
        })

    if not rows and not errors:
        errors.append("CSV did not contain any lead rows.")

    missing_all_known_headers = not any(
        alias in normalized_headers
        for aliases in CSV_ALIASES.values()
        for alias in aliases
    )
    if missing_all_known_headers:
        errors.append("CSV headers were not recognized. Use headers like name, business_name, phone, email, source, notes.")

    return rows, errors

def employee_required(view):
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_employee_or_admin():
            messages.error(request, "Employee access required.")
            return redirect("portal_home")
        return view(request, *args, **kwargs)
    return wrapper

@employee_required
def crm_home(request):
    leads = Lead.objects.filter(lead_type="internal_sales")
    return render(request, "crm/crm_home.html", {"leads": leads})

@employee_required
def lead_create(request):
    if request.method == "POST":
        form = LeadForm(request.POST)
        if form.is_valid():
            lead = form.save(commit=False)
            lead.lead_type = "internal_sales"
            lead.client = None
            lead.ai_instance = None
            lead.save()
            messages.success(request, "Lead created.")
            return redirect("crm_home")
    else:
        form = LeadForm()
    return render(request, "crm/lead_form.html", {"form": form})


@employee_required
def lead_upload(request):
    import_errors = []
    if request.method == "POST":
        form = LeadCSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            rows, import_errors = parse_internal_lead_csv(form.cleaned_data["csv_file"])
            if not import_errors:
                with transaction.atomic():
                    Lead.objects.bulk_create([Lead(**row) for row in rows])
                messages.success(request, f"Imported {len(rows)} internal sales lead{'s' if len(rows) != 1 else ''}.")
                return redirect("crm_home")
    else:
        form = LeadCSVUploadForm()
    return render(request, "crm/lead_upload.html", {
        "form": form,
        "import_errors": import_errors[:25],
        "sample_headers": "name,business_name,industry,phone,email,source,status,notes,value,follow_up_date,assigned_to",
    })

@employee_required
def lead_detail(request, pk):
    lead = get_object_or_404(Lead, pk=pk, lead_type="internal_sales")
    if request.method == "POST":
        form = LeadNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.lead = lead
            note.user = request.user
            note.save()
            messages.success(request, "Note added.")
            return redirect("lead_detail", pk=lead.pk)
    else:
        form = LeadNoteForm()
    return render(request, "crm/lead_detail.html", {"lead": lead, "note_form": form})

@employee_required
def lead_edit(request, pk):
    lead = get_object_or_404(Lead, pk=pk, lead_type="internal_sales")
    if request.method == "POST":
        form = LeadForm(request.POST, instance=lead)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.lead_type = "internal_sales"
            updated.client = None
            updated.ai_instance = None
            updated.save()
            messages.success(request, "Lead updated.")
            return redirect("lead_detail", pk=lead.pk)
    else:
        form = LeadForm(instance=lead)
    return render(request, "crm/lead_form.html", {"form": form, "lead": lead})
