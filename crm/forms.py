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
