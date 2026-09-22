from django import forms
from django.conf import settings
from django.core.validators import URLValidator
from django.contrib.auth import get_user_model
from .models import Lead, LeadNote


User = get_user_model()


def sales_staff_queryset():
    return User.objects.filter(role__in=["employee", "admin"], is_active=True).order_by("first_name", "username")


LEAD_FINDER_INDUSTRIES = [
    "Cannabis",
    "Law Firm",
    "Insurance",
    "Real Estate",
    "Roofing",
    "Solar",
    "HVAC",
    "Dentist",
    "Chiropractor",
    "Medical Spa",
    "Salon",
    "Barbershop",
    "Auto Repair",
    "Car Dealership",
    "Restaurant",
    "Accounting",
    "Construction",
    "Financial Advisor",
    "Mortgage",
    "Home Services",
]

LEAD_FINDER_QUANTITIES = [5, 10, 15, 20, 25, 50, 100, 250, 500, 1000]


class LeadFinderForm(forms.Form):
    industry = forms.ChoiceField(
        choices=[(industry, industry) for industry in LEAD_FINDER_INDUSTRIES] + [("other", "Other…")],
        widget=forms.Select(attrs={"data-lead-finder-industry": "true"}),
    )
    custom_industry = forms.CharField(
        required=False,
        max_length=150,
        label="Custom industry",
        widget=forms.TextInput(attrs={"placeholder": "Enter industry", "data-custom-industry": "true"}),
    )
    location = forms.CharField(
        required=False,
        max_length=180,
        widget=forms.TextInput(attrs={"placeholder": "City, state — e.g. San Diego, CA"}),
    )
    quantity = forms.ChoiceField(choices=[(str(value), str(value)) for value in LEAD_FINDER_QUANTITIES], initial="10")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not settings.CELERY_BROKER_URL:
            self.fields["quantity"].choices = [(str(n), str(n)) for n in LEAD_FINDER_QUANTITIES if n <= 20]

    def clean(self):
        cleaned = super().clean()
        industry = cleaned.get("industry")
        custom = (cleaned.get("custom_industry") or "").strip()
        if industry == "other":
            if not custom:
                self.add_error("custom_industry", "Enter the custom industry.")
            cleaned["industry"] = custom
        cleaned["location"] = (cleaned.get("location") or "").strip()
        cleaned["quantity"] = int(cleaned.get("quantity") or 0)
        return cleaned


class SalesUpdateForm(forms.Form):
    outcome = forms.ChoiceField(choices=[("", "Choose an outcome"), ("attempted", "Tried to reach them"), ("warm_lead", "Had a conversation"), ("callback_requested", "Follow up later"), ("not_interested", "Not interested"), ("do_not_contact", "Do not contact"), ("closed_won", "Won")])
    note = forms.CharField(max_length=4000, required=False, widget=forms.Textarea(attrs={"rows":3,"placeholder":"What did you learn?"}))
    follow_up_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type":"date"}))

    def clean(self):
        values = super().clean()
        if values.get("outcome") == "callback_requested" and not values.get("follow_up_date"):
            self.add_error("follow_up_date", "Choose when to follow up.")
        return values


class AssessmentForm(forms.Form):
    workflow = forms.CharField(label="How the business operates today", max_length=2000, required=False, widget=forms.Textarea(attrs={"rows":3}))
    tools = forms.CharField(label="Current tools and systems", max_length=1000, required=False)
    bottleneck = forms.CharField(label="Main bottleneck", max_length=2000, required=False, widget=forms.Textarea(attrs={"rows":2}))
    goal = forms.CharField(label="Desired outcome", max_length=1000, required=False)
    appointment_at = forms.DateTimeField(label="Confirmed assessment time", required=False, widget=forms.DateTimeInput(attrs={"type":"datetime-local"},format="%Y-%m-%dT%H:%M"))
    meeting_url = forms.URLField(label="Video meeting link", required=False, validators=[URLValidator(schemes=["https", "http"])])
    confirmed = forms.BooleanField(label="This time has been agreed and booked with the customer", required=False)
    completed = forms.BooleanField(label="Assessment completed", required=False)
    strategy = forms.CharField(label="Proposed implementation strategy", max_length=4000, required=False, widget=forms.Textarea(attrs={"rows":3}))
    pricing = forms.CharField(label="Custom pricing / scope notes", max_length=2000, required=False, widget=forms.Textarea(attrs={"rows":2}))

    def clean(self):
        values = super().clean()
        if values.get("confirmed") and not values.get("appointment_at"):
            self.add_error("appointment_at", "Enter the confirmed date and time.")
        if values.get("appointment_at") and not values.get("confirmed"):
            self.add_error("confirmed", "Confirm the booking before recording an assessment time.")
        if values.get("completed") and not values.get("confirmed"):
            self.add_error("completed", "Record the confirmed assessment before marking it completed.")
        return values


class RestrictedLeadForm(forms.ModelForm):
    def clean(self):
        values = super().clean()
        if self.instance.pk and self.instance.status == "do_not_contact" and values.get("status") != "do_not_contact" and not self.is_sales_manager:
            self.add_error("status", "A manager must review the do-not-contact restriction before outreach resumes.")
        return values


class LeadForm(RestrictedLeadForm):
    class Meta:
        model = Lead
        fields = [
            "name", "business_name", "industry", "phone", "email", "website",
            "address", "city", "state", "zip_code", "point_of_contact", "contact_role",
            "source", "status", "lead_temperature", "notes", "cleaned_notes", "value",
            "assigned_to", "follow_up_date", "needs_review", "archived",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
            "cleaned_notes": forms.Textarea(attrs={"rows": 4}),
            "follow_up_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, user=None, is_sales_manager=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.is_sales_manager = is_sales_manager
        self.fields["assigned_to"].queryset = sales_staff_queryset()
        if user and not is_sales_manager:
            self.fields["assigned_to"].queryset = User.objects.filter(pk=user.pk)
            self.fields["assigned_to"].initial = user
            self.fields["assigned_to"].disabled = True
            self.fields["assigned_to"].help_text = "SDR leads are automatically assigned to you."

class LeadNoteForm(forms.ModelForm):
    class Meta:
        model = LeadNote
        fields = ["note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}


class LeadCSVUploadForm(forms.Form):
    csv_file = forms.FileField(
        label="CSV or Excel file",
        help_text="Upload a .csv or .xlsx file with headers like business_name, phone, email, industry, notes, status, assigned_to.",
    )
    sheet_name = forms.CharField(
        required=False,
        label="Sheet name",
        help_text="Optional for Excel files. Leave blank to import all visible sheets.",
    )
    default_assigned_to = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label="Assign this upload to",
        help_text="Optional. Rows with an assigned_to/SDR column keep that row value; every other imported row goes to this SDR.",
    )

    def __init__(self, *args, user=None, is_sales_manager=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.is_sales_manager = is_sales_manager
        if user and not is_sales_manager:
            self.fields["default_assigned_to"].empty_label = None
            self.fields["default_assigned_to"].queryset = User.objects.filter(pk=user.pk)
            self.fields["default_assigned_to"].initial = user
            self.fields["default_assigned_to"].disabled = True
            self.fields["default_assigned_to"].help_text = "Uploads from SDR accounts are automatically assigned to that SDR. Sheet-level owner columns are ignored for privacy."
        else:
            self.fields["default_assigned_to"].empty_label = "Leave unassigned / use sheet column"
            self.fields["default_assigned_to"].queryset = sales_staff_queryset()

    def clean_csv_file(self):
        uploaded = self.cleaned_data["csv_file"]
        allowed = (".csv", ".xlsx")
        if not uploaded.name.lower().endswith(allowed):
            raise forms.ValidationError("Upload a .csv or .xlsx file.")
        if uploaded.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Import file is too large. Please upload a file under 5 MB.")
        return uploaded


class LeadIntelligenceForm(RestrictedLeadForm):
    correction_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Optional note explaining why you changed the classification.",
    )

    class Meta:
        model = Lead
        fields = [
            "status", "lead_temperature", "cleaned_notes", "assigned_to",
            "follow_up_date", "needs_review", "point_of_contact", "contact_role",
        ]
        widgets = {
            "cleaned_notes": forms.Textarea(attrs={"rows": 4}),
            "follow_up_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, user=None, is_sales_manager=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.is_sales_manager = is_sales_manager
        self.fields["assigned_to"].queryset = sales_staff_queryset()
        if user and not is_sales_manager:
            self.fields["assigned_to"].queryset = User.objects.filter(pk=user.pk)
            self.fields["assigned_to"].initial = user
            self.fields["assigned_to"].disabled = True
            self.fields["assigned_to"].help_text = "Only owner/admin users can reassign SDR leads."
