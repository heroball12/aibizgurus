import re

from django import forms
from django.contrib.auth import get_user_model

from .models import TimeClockEntry


User = get_user_model()


def active_staff_queryset():
    return User.objects.filter(role__in=["employee", "admin", "owner"], is_active=True).order_by("first_name", "username")


class StaffUserForm(forms.ModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text="Leave blank when editing to keep the current password. New staff default to AIBG123.",
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "role", "is_active", "password"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["role"].choices = [("employee", "Employee / SDR"), ("admin", "Admin")]

    def clean_first_name(self):
        first_name = self.cleaned_data["first_name"].strip()
        if not first_name:
            raise forms.ValidationError("First name is required.")
        return first_name

    def clean(self):
        cleaned = super().clean()
        first_name = cleaned.get("first_name", "")
        username = self.email_for_first_name(first_name)
        if username:
            existing = User.objects.filter(username=username).exclude(pk=self.instance.pk).first()
            if existing:
                raise forms.ValidationError(f"{username} already exists. Edit that staff account instead.")
        return cleaned

    @staticmethod
    def email_for_first_name(first_name):
        slug = re.sub(r"[^a-z0-9]+", "", (first_name or "").strip().lower())
        return f"{slug}@aibiz.guru" if slug else ""

    def save(self, commit=True):
        user = super().save(commit=False)
        email = self.email_for_first_name(user.first_name)
        user.username = email
        user.email = email
        user.is_staff = True
        user.is_superuser = False
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        elif not user.pk:
            user.set_password("AIBG123")
        if commit:
            user.save()
        return user


class StaffMessageThreadForm(forms.Form):
    title = forms.CharField(
        required=False,
        max_length=180,
        help_text="Optional for group chats. One-on-one chats can stay unnamed.",
    )
    participants = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        label="Send to",
        widget=forms.CheckboxSelectMultiple,
        help_text="Choose one or more staff members.",
    )
    message = forms.CharField(
        label="Message",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Type the first message…"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = active_staff_queryset()
        if user and user.pk:
            queryset = queryset.exclude(pk=user.pk)
        self.fields["participants"].queryset = queryset

    def clean_message(self):
        return self.cleaned_data.get("message", "").strip()


class StaffMessageForm(forms.Form):
    body = forms.CharField(
        label="Message",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Write a reply…"}),
    )

    def clean_body(self):
        return self.cleaned_data.get("body", "").strip()


class TimeClockNoteForm(forms.Form):
    note = forms.CharField(
        required=False,
        max_length=255,
        label="Note",
        widget=forms.TextInput(attrs={"placeholder": "Optional note for this shift"}),
    )


class TimeClockEntryForm(forms.ModelForm):
    class Meta:
        model = TimeClockEntry
        fields = ["clock_in", "clock_out", "note"]
        widgets = {
            "clock_in": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "clock_out": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "note": forms.TextInput(attrs={"placeholder": "Optional shift note"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["clock_in"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["clock_out"].input_formats = ["%Y-%m-%dT%H:%M"]
        if self.instance and self.instance.pk:
            self.initial["clock_in"] = self.instance.clock_in.astimezone().strftime("%Y-%m-%dT%H:%M")
            if self.instance.clock_out:
                self.initial["clock_out"] = self.instance.clock_out.astimezone().strftime("%Y-%m-%dT%H:%M")

    def clean(self):
        cleaned = super().clean()
        clock_in = cleaned.get("clock_in")
        clock_out = cleaned.get("clock_out")
        if clock_in and clock_out and clock_out < clock_in:
            raise forms.ValidationError("Clock out must be after clock in.")
        return cleaned
