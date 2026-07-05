from django import forms
from .models import ConsultationRequest

class ConsultationRequestForm(forms.ModelForm):
    class Meta:
        model = ConsultationRequest
        fields = ["name", "email", "phone", "business_name", "industry", "message"]
        widgets = {"message": forms.Textarea(attrs={"rows": 4})}
