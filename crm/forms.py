from django import forms
from django.contrib.auth import get_user_model
from .models import Lead, LeadNote


User = get_user_model()


def sales_staff_queryset():
    return User.objects.filter(role__in=["employee", "admin"], is_active=True).order_by("first_name", "username")


class LeadForm(forms.ModelForm):
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


class LeadIntelligenceForm(forms.ModelForm):
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
