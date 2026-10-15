"""Validated pipeline selection shared by the screen and spreadsheet exports."""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import CharField, DateTimeField, F, OuterRef, Q, Subquery, Value
from django.db.models.functions import Cast, Coalesce, Greatest, NullIf
from django.utils import timezone

from audit.models import ActivityLog, EmployeeLeadEvent
from .models import Lead, LeadActivity, LeadNote
from .sales import INACTIVE, STAGES, due_filter


def date_field(label):
    return forms.DateField(required=False, label=label, widget=forms.DateInput(attrs={"type": "date"}),
                           validators=[MinValueValidator(date(1970, 1, 1)), MaxValueValidator(date(2100, 12, 31))])


class PipelineFilterForm(forms.Form):
    q = forms.CharField(required=False, max_length=200, label="Search",
                        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Business, contact, phone, email or notes…"}))
    assigned_to = forms.ChoiceField(required=False, label="Assigned to")
    activity = forms.ChoiceField(required=False, label="Last activity", choices=[
        ("", "Any activity"), ("today", "Active today"), ("7", "Active in the last 7 days"),
        ("30", "Active in the last 30 days"), ("stale7", "Inactive for 7+ days"),
        ("stale14", "Inactive for 14+ days"), ("stale30", "Inactive for 30+ days"),
        ("never", "No recorded activity"),
    ])
    sort = forms.ChoiceField(required=False, initial="newest", label="Sort by", choices=[
        ("newest", "Newest leads"), ("oldest", "Oldest leads"),
        ("activity_newest", "Most recent activity"), ("activity_oldest", "Oldest activity"),
        ("contact_newest", "Most recent contact"), ("followup", "Follow-up date"),
        ("appointment", "Assessment date"), ("assigned", "Assigned employee"), ("business", "Business name"),
    ])
    status = forms.ChoiceField(required=False, choices=[("", "All statuses"), *Lead.STATUS_CHOICES])
    temperature = forms.ChoiceField(required=False, choices=[("", "All temperatures"), *Lead._meta.get_field("lead_temperature").choices])
    industry = forms.ChoiceField(required=False)
    city = forms.CharField(required=False, max_length=120, label="City contains")
    state = forms.ChoiceField(required=False)
    lead_source = forms.ChoiceField(required=False, label="Lead source")
    source_file = forms.ChoiceField(required=False, label="Source file")
    source_sheet = forms.ChoiceField(required=False, label="Source sheet")
    follow_up = forms.ChoiceField(required=False, label="Follow-up", choices=[
        ("", "Any follow-up"), ("due", "Due now / overdue"), ("today", "Due today"),
        ("next7", "Scheduled in the next 7 days"), ("missing", "No follow-up scheduled"),
    ])
    appointment = forms.ChoiceField(required=False, label="Growth Assessment", choices=[
        ("", "Any assessment"), ("upcoming", "Upcoming appointment"),
        ("past", "Past appointment"), ("missing", "No appointment recorded"),
    ])
    contacted = forms.ChoiceField(required=False, label="Contact history", choices=[
        ("", "Any contact history"), ("yes", "Has a recorded contact date"), ("no", "No recorded contact date"),
    ])
    phone = forms.ChoiceField(required=False, label="Phone", choices=[("", "Any phone"), ("yes", "Has phone"), ("no", "Missing phone")])
    email = forms.ChoiceField(required=False, label="Email", choices=[("", "Any email"), ("yes", "Has email"), ("no", "Missing email")])
    website = forms.ChoiceField(required=False, label="Website", choices=[("", "Any website"), ("yes", "Has website"), ("no", "Missing website")])
    needs_review = forms.ChoiceField(required=False, label="Review", choices=[
        ("", "Any review status"), ("yes", "Needs review"), ("no", "No review flag"),
    ])
    activity_from = date_field("Last activity from")
    activity_to = date_field("Last activity through")
    created_from = date_field("Lead added from")
    created_to = date_field("Lead added through")

    def __init__(self, data=None, *, base, user):
        super().__init__(data)
        from .views import is_sales_manager
        staff = get_user_model().objects.filter(
            Q(pk__in=base.values("assigned_to_id")) | Q(is_active=True, role__in=["owner", "admin", "employee"])
        ).order_by("first_name", "username")
        if not is_sales_manager(user):
            staff = staff.filter(pk=user.pk)
        self.fields["assigned_to"].choices = [("", "All employees"), ("unassigned", "Unassigned")] + [
            (str(person.pk), (person.get_full_name() or person.username) + (" (inactive)" if not person.is_active else ""))
            for person in staff
        ]
        for field, label in [("industry", "industries"), ("state", "states"), ("lead_source", "sources"),
                             ("source_file", "files"), ("source_sheet", "sheets")]:
            model_field = "source" if field == "lead_source" else field
            values = base.exclude(**{model_field: ""}).order_by(model_field).values_list(model_field, flat=True).distinct()
            self.fields[field].choices = [("", "All " + label), *[(value, value) for value in values]]

    def clean(self):
        data = super().clean()
        for prefix in ("activity", "created"):
            start, end = data.get(prefix + "_from"), data.get(prefix + "_to")
            if start and end and start > end:
                self.add_error(prefix + "_to", "Choose an end date on or after the start date.")
        return data


def with_last_activity(leads):
    """Use recorded work, including history; creation/import alone is not work.

    Separate indexed subqueries avoid join multiplication and duplicate leads.
    Coalesce each operand because SQLite and PostgreSQL differ on NULL greatest.
    """
    epoch = Value(datetime(1970, 1, 1, tzinfo=dt_timezone.utc), output_field=DateTimeField())
    histories = [
        LeadActivity.objects.filter(lead_id=OuterRef("pk")).exclude(activity_type="imported_note"),
        LeadNote.objects.filter(lead_id=OuterRef("pk")),
        EmployeeLeadEvent.objects.filter(lead_id=OuterRef("pk"), kind="updated"),
        ActivityLog.objects.filter(model_label="crm.Lead", object_id=Cast(OuterRef("pk"), CharField()), action="update"),
    ]
    dates = [Coalesce(Subquery(q.order_by("-created_at").values("created_at")[:1]), epoch) for q in histories]
    dates.append(Coalesce(F("last_contact_at"), epoch))
    return leads.annotate(last_activity_at=NullIf(Greatest(*dates), epoch))


def midnight(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def pipeline_selection(request, base):
    """Return form, results before stage selection, staged results and stage."""
    form = PipelineFilterForm(request.GET, base=base, user=request.user)
    stage = request.GET.get("stage", "all")
    if stage not in {key for key, _, _ in STAGES} | {"all", "due"}:
        stage = "all"
    leads = with_last_activity(base)
    if not form.is_valid():
        return form, leads.none(), leads.none(), stage
    data = form.cleaned_data
    from .views import apply_lead_filters
    leads = apply_lead_filters(leads, data)
    for field in ("industry", "state", "lead_source"):
        if data[field]:
            leads = leads.filter(**{"source" if field == "lead_source" else field: data[field]})
    if data["city"]:
        leads = leads.filter(city__icontains=data["city"])
    now, today = timezone.now(), timezone.localdate()
    activity = data["activity"]
    if activity == "never":
        leads = leads.filter(last_activity_at__isnull=True)
    elif activity == "today":
        leads = leads.filter(last_activity_at__gte=midnight(today), last_activity_at__lt=midnight(today + timedelta(days=1)))
    elif activity in {"7", "30"}:
        leads = leads.filter(last_activity_at__gte=now - timedelta(days=int(activity)), last_activity_at__lte=now)
    elif activity.startswith("stale"):
        # Do not call a brand-new untouched lead stale.
        leads = leads.alias(last_touch_or_added=Coalesce("last_activity_at", "created_at")).filter(
            last_touch_or_added__lte=now - timedelta(days=int(activity[5:])))
    for prefix, field in (("activity", "last_activity_at"), ("created", "created_at")):
        if data[prefix + "_from"]:
            leads = leads.filter(**{field + "__gte": midnight(data[prefix + "_from"])})
        if data[prefix + "_to"]:
            leads = leads.filter(**{field + "__lt": midnight(data[prefix + "_to"] + timedelta(days=1))})
    follow_up = data["follow_up"]
    if follow_up:
        leads = leads.exclude(status__in=INACTIVE)
        if follow_up == "due":
            leads = leads.filter(due_filter())
        elif follow_up in {"today", "next7"}:
            end = today if follow_up == "today" else today + timedelta(days=7)
            leads = leads.filter(Q(follow_up_date__range=(today, end)) |
                                 Q(next_follow_up_at__gte=midnight(today), next_follow_up_at__lt=midnight(end + timedelta(days=1))))
        else:
            leads = leads.filter(follow_up_date__isnull=True, next_follow_up_at__isnull=True)
    if data["appointment"] == "upcoming":
        leads = leads.filter(appointment_at__gte=now)
    elif data["appointment"] == "past":
        leads = leads.filter(appointment_at__lt=now)
    elif data["appointment"] == "missing":
        leads = leads.filter(appointment_at__isnull=True)
    if data["contacted"]:
        leads = leads.filter(last_contact_at__isnull=data["contacted"] == "no")
    for field in ("phone", "email", "website"):
        if data[field] == "yes":
            leads = leads.exclude(**{field: ""})
        elif data[field] == "no":
            leads = leads.filter(**{field: ""})
    if data["needs_review"]:
        leads = leads.filter(needs_review=data["needs_review"] == "yes")
    filtered = leads
    if stage == "due":
        leads = leads.exclude(status__in=INACTIVE).filter(due_filter())
    elif stage != "all":
        leads = leads.filter(status__in=next(items for key, _, items in STAGES if key == stage))
    sort = data["sort"] or "newest"
    order = {
        "newest": F("created_at").desc(), "oldest": F("created_at").asc(),
        "activity_newest": F("last_activity_at").desc(nulls_last=True),
        "activity_oldest": F("last_activity_at").asc(nulls_last=True),
        "contact_newest": F("last_contact_at").desc(nulls_last=True),
        "followup": F("follow_up_date").asc(nulls_last=True), "appointment": F("appointment_at").asc(nulls_last=True),
        "assigned": F("assigned_to__first_name").asc(nulls_last=True), "business": F("business_name").asc(),
    }[sort]
    return form, filtered, leads.order_by(order, "-pk"), stage
