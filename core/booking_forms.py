from datetime import timedelta

from django import forms
from django.utils import timezone

from .booking_models import OfficeSchedule, OfficeClosure


class OfficeBookingForm(forms.Form):
    starts_at = forms.DateTimeField(widget=forms.HiddenInput)
    submission_token = forms.CharField(widget=forms.HiddenInput, max_length=300)
    name = forms.CharField(label="Your name", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    phone = forms.CharField(max_length=80, widget=forms.TextInput(attrs={"type": "tel", "autocomplete": "tel"}))
    business_name = forms.CharField(label="Business name", max_length=200, widget=forms.TextInput(attrs={"autocomplete": "organization"}))
    industry = forms.CharField(max_length=150)
    message = forms.CharField(label="What would you like to explore?", max_length=3000, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    website_confirm = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs["id"] = "office_" + name

    def clean_website_confirm(self):
        if self.cleaned_data.get("website_confirm"):
            raise forms.ValidationError("Please reload the page and try again.")
        return ""


class OfficeScheduleForm(forms.ModelForm):
    weekdays = forms.TypedMultipleChoiceField(coerce=int, choices=list(enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])), widget=forms.CheckboxSelectMultiple)
    duration_minutes = forms.IntegerField(min_value=15, max_value=120, label="Appointment length (minutes)")
    buffer_minutes = forms.IntegerField(min_value=0, max_value=120, label="Gap after each appointment (minutes)")
    notice_hours = forms.IntegerField(min_value=0, max_value=168, label="Minimum advance notice (hours)")
    horizon_days = forms.IntegerField(min_value=1, max_value=90, label="Allow bookings this many days ahead")
    notification_email = forms.EmailField(label="Owner notification email")

    class Meta:
        model = OfficeSchedule
        fields = ["enabled", "notification_email", "weekdays", "opens_at", "closes_at", "duration_minutes", "buffer_minutes", "notice_hours", "horizon_days"]
        widgets = {"opens_at": forms.TimeInput(attrs={"type": "time"}), "closes_at": forms.TimeInput(attrs={"type": "time"})}

    def clean(self):
        data = super().clean()
        opening, closing = data.get("opens_at"), data.get("closes_at")
        if opening and closing:
            available = (closing.hour * 60 + closing.minute) - (opening.hour * 60 + opening.minute)
            if available < data.get("duration_minutes", 30) + data.get("buffer_minutes", 30):
                raise forms.ValidationError("Office hours must allow at least one appointment and its gap, on the same day.")
        return data


class OfficeClosureForm(forms.ModelForm):
    class Meta:
        model = OfficeClosure
        fields = ["starts_at", "ends_at", "reason"]
        widgets = {name: forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M") for name in ("starts_at", "ends_at")}

    def clean(self):
        data = super().clean()
        start, end = data.get("starts_at"), data.get("ends_at")
        if start and end and (end <= start or end < timezone.now() or end - start > timedelta(days=365)):
            raise forms.ValidationError("Choose a future block with an end after its start, up to one year long.")
        return data
