from django import forms
from .models import Lead, LeadNote

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
