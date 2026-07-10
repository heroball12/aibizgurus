from django import forms
from .models import Lead, LeadNote

class LeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = ["name", "business_name", "industry", "phone", "email", "source", "status", "notes", "value", "assigned_to", "follow_up_date"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4}), "follow_up_date": forms.DateInput(attrs={"type": "date"})}

class LeadNoteForm(forms.ModelForm):
    class Meta:
        model = LeadNote
        fields = ["note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}


class LeadCSVUploadForm(forms.Form):
    csv_file = forms.FileField(
        label="CSV file",
        help_text="Upload a .csv file with headers like name, business_name, phone, email, industry, source, notes, value, status.",
    )

    def clean_csv_file(self):
        uploaded = self.cleaned_data["csv_file"]
        if not uploaded.name.lower().endswith(".csv"):
            raise forms.ValidationError("Upload a .csv file.")
        if uploaded.size > 2 * 1024 * 1024:
            raise forms.ValidationError("CSV file is too large. Please upload a file under 2 MB.")
        return uploaded
