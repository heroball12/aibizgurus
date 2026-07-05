from django import forms
from .models import ClientAccount, BusinessProfile, AIInstance, Integration

class ClientAccountForm(forms.ModelForm):
    class Meta:
        model = ClientAccount
        fields = ["business_name", "industry", "owner_name", "contact_email", "contact_phone", "website", "status", "plan"]

class BusinessProfileForm(forms.ModelForm):
    class Meta:
        model = BusinessProfile
        fields = ["hours","services","products","faqs","service_area","policies","booking_instructions","escalation_instructions","brand_voice","extra_context"]
        widgets = {f: forms.Textarea(attrs={"rows": 4}) for f in fields if f != "brand_voice"}

class AIInstanceForm(forms.ModelForm):
    class Meta:
        model = AIInstance
        fields = [
            "name", "greeting", "system_prompt", "tone", "model",
            "openai_api_mode", "widget_primary_color",
            "collect_name", "collect_phone", "collect_email",
        ]
        widgets = {
            "greeting": forms.Textarea(attrs={"rows": 3}),
            "system_prompt": forms.Textarea(attrs={"rows": 6}),
            "widget_primary_color": forms.TextInput(attrs={"type": "color"}),
        }


class ActivatedAIInstanceForm(AIInstanceForm):
    class Meta(AIInstanceForm.Meta):
        fields = AIInstanceForm.Meta.fields + ["status", "embed_enabled", "voice_enabled", "sms_enabled"]

class IntegrationForm(forms.ModelForm):
    api_key = forms.CharField(
        required=False,
        label="OpenAI API key (optional)",
        help_text="Leave blank to use the AI Business Gurus platform key.",
        widget=forms.PasswordInput(render_value=False),
    )
    account_sid = forms.CharField(required=False, label="Twilio account SID")
    auth_token = forms.CharField(required=False, label="Twilio auth token", widget=forms.PasswordInput(render_value=False))
    phone_number = forms.CharField(required=False, label="Twilio phone / from number")

    class Meta:
        model = Integration
        fields = ["integration_type", "name", "is_active", "notes"]

    def clean(self):
        cleaned = super().clean()
        integration_type = cleaned.get("integration_type")
        if integration_type == "twilio" and cleaned.get("is_active"):
            existing = self.instance if self.instance and self.instance.pk else None
            for field in ["account_sid", "auth_token", "phone_number"]:
                if not cleaned.get(field) and not (existing and existing.get_credential(field)):
                    self.add_error(field, "Required to activate Twilio.")
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        for f in ["api_key", "account_sid", "auth_token", "phone_number"]:
            val = self.cleaned_data.get(f)
            if val:
                obj.set_credential(f, val)
        if commit:
            obj.save()
        return obj
