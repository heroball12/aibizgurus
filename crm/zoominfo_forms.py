from datetime import timedelta
import re

from django import forms
from django.utils import timezone

from .directory_locations import US_STATES
from .forms import sales_staff_queryset
from .views import is_sales_manager


class SearchForm(forms.Form):
    company_name = forms.CharField(required=False, max_length=200, label="Company name")
    company_id = forms.RegexField(r"^[1-9][0-9]{0,17}$", required=False, label="ZoomInfo company ID")
    website = forms.URLField(required=False, label="Company website", assume_scheme="https")
    person_name = forms.CharField(required=False, max_length=200, label="Person's name")
    job_title = forms.CharField(required=False, max_length=200, label="Job title", help_text="For example: Owner OR President")
    management_level = forms.ChoiceField(required=False, label="Seniority", choices=[("", "Any level")] + [(x,x) for x in ["Board Member", "C Level Exec", "VP Level Exec", "Director", "Manager", "Non Manager"]])
    contact_details = forms.ChoiceField(required=False, label="Contact availability", choices=[("", "Any available profile"), ("email", "Business email"), ("directPhone", "Direct phone"), ("mobilePhone", "Mobile phone"), ("email,directPhone", "Email and direct phone")], help_text="Filters availability hints. Retrieving contact details is a separate, reviewed step.")
    topics = forms.MultipleChoiceField(required=True, label="Intent topics", widget=forms.SelectMultiple(attrs={"size": 8}))
    start_date = forms.DateField(label="Signals from", widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(label="Through", widget=forms.DateInput(attrs={"type": "date"}))
    min_score = forms.IntegerField(min_value=60, max_value=100, initial=70, label="Minimum signal score")
    industry = forms.CharField(required=False, max_length=200, label="Industry keywords", help_text="Use OR to broaden: insurance OR insurance brokers", widget=forms.TextInput(attrs={"placeholder": "Insurance, restaurants, HVAC…"}))
    state = forms.ChoiceField(required=False, choices=[("", "All US states")] + sorted(US_STATES.items(), key=lambda item:item[1]))
    zip_code = forms.RegexField(r"^\d{5}(?:-\d{4})?$", required=False, label="ZIP code")
    radius = forms.TypedChoiceField(required=False, coerce=int, empty_value=None, label="ZIP radius", choices=[("", "Exact ZIP")] + [(str(n),f"{n} miles") for n in [10,25,50,100,250]])
    max_employees = forms.IntegerField(required=False, min_value=1, max_value=10000000, label="Maximum company employees")
    page_size = forms.TypedChoiceField(required=False, coerce=int, empty_value=50, initial=50, label="Matches per page", choices=[(25, "25 matches"), (50, "50 matches"), (100, "100 matches")])
    sort_order = forms.ChoiceField(required=False, label="Sort matches")
    exclude_major_chains = forms.BooleanField(required=False, initial=True, label="Hide major chains", help_text="Hides recognized national brands and franchises. Some chains may still appear.")

    def __init__(self, *args, kind="companies", topics=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.kind = kind
        intent_fields = {"topics", "start_date", "end_date", "min_score"}
        person_fields = {"person_name", "job_title", "management_level", "contact_details"}
        if kind != "intent":
            for name in intent_fields:
                self.fields.pop(name)
        else:
            self.fields.pop("page_size")
            self.fields.pop("sort_order")
            self.fields["topics"].choices = [(name, name + (f" · {category}" if category else "")) for name, category in topics]
            self.fields["start_date"].initial = (timezone.localdate() - timedelta(days=14)).isoformat()
            self.fields["end_date"].initial = timezone.localdate().isoformat()
            for name in {"company_name", "company_id", "website"}:
                self.fields.pop(name)
        if kind != "people":
            for name in person_fields:
                self.fields.pop(name)
        if kind != "intent":
            self.fields["sort_order"].choices = ([("-relevance", "Most relevant"), ("-contactAccuracyScore", "Highest contact accuracy"), ("companyName", "Company name")]
                if kind == "people" else [("name", "Company name"), ("-employeeCount", "Largest team"), ("-revenue", "Highest revenue")])
            self.fields["sort_order"].initial = self.fields["sort_order"].choices[0][0]
            self.fields["state"].help_text = "Leave ZIP blank to search the whole state, or leave both blank for the US."
            self.fields["radius"].help_text = "Search nearby businesses using a ZIP radius, up to 250 miles."

    def clean(self):
        values = super().clean()
        title = values.get("job_title", "")
        if title and not re.fullmatch(r"[\w\s+&,./'\-\"]+", title):
            self.add_error("job_title", "Use words without parentheses or special search operators.")
        if values.get("radius") and not values.get("zip_code"):
            self.add_error("zip_code", "Enter a ZIP code to use a radius.")
        if self.kind == "intent":
            if len(values.get("topics", [])) > 50:
                self.add_error("topics", "Choose up to 50 topics.")
            start, end = values.get("start_date"), values.get("end_date")
            if start and end and start > end:
                self.add_error("end_date", "End date must be on or after the start date.")
            if end and end > timezone.localdate():
                self.add_error("end_date", "Choose today or an earlier date.")
        elif not any(values.get(k) for k in ["company_name", "company_id", "website", "person_name", "job_title", "management_level", "industry", "state", "zip_code", "max_employees"]):
            raise forms.ValidationError("Enter at least one search filter.")
        return values

    def criteria(self):
        d = self.cleaned_data
        mapping = {"company_name": "companyName", "company_id": "companyId", "website": "companyWebsite", "person_name": "fullName", "job_title": "jobTitle", "management_level": "managementLevel", "industry": "industryKeywords", "zip_code": "zipCode"}
        result = {api: d[name] for name, api in mapping.items() if d.get(name)}
        result["country"] = "United States"
        if d.get("state"):
            result["state"] = US_STATES[d["state"]]
        if d.get("radius"):
            result["zipCodeRadiusMiles"] = d["radius"]
        if d.get("max_employees"):
            result["employeeRangeMax"] = str(d["max_employees"])
        if self.kind == "people":
            result["locationSearchType"] = "HQ"
            if d.get("contact_details"):
                result["requiredFields"] = d["contact_details"]
        if self.kind == "companies":
            result["excludeDefunctCompanies"] = True
        if self.kind == "intent":
            result.update(topics=d["topics"], signalStartDate=d["start_date"].isoformat(), signalEndDate=d["end_date"].isoformat(),
                          signalScoreMin=d["min_score"], signalScoreMax=100, findRecommendedContacts=False)
        return result

    def clean_sort_order(self):
        return self.cleaned_data.get("sort_order") or self.fields["sort_order"].choices[0][0]

    def snapshot(self):
        return {k: v.isoformat() if hasattr(v, "isoformat") else v for k,v in self.cleaned_data.items()}


class AssignForm(forms.Form):
    assigned_to = forms.ModelChoiceField(queryset=sales_staff_queryset(), required=False, label="Assign leads to", empty_label="Unassigned")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if not is_sales_manager(user):
            self.fields.pop("assigned_to")

    def assignee(self):
        return self.cleaned_data.get("assigned_to") if is_sales_manager(self.user) else self.user
