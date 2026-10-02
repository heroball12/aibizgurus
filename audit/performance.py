"""Date-scoped employee activity, kept separate from current pipeline totals."""
from datetime import datetime, time, timedelta
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date

from crm.models import Lead, LeadGenerationBatch, LeadImport
from training.models import EmployeeProgress
from .models import ActivityLog, EmployeeLeadEvent, TimeClockEntry

CLOSED = {"closed_won", "closed_lost", "not_interested", "do_not_contact", "permanently_closed", "client_onboarded"}
COLUMNS = [
    ("calls", "Calls / updates"), ("worked", "Leads worked"), ("booked", "Assessments booked"),
    ("completed", "Assessments completed"), ("booking_rate", "Booking rate %"),
    ("hours", "Clocked hours"), ("calls_per_hour", "Calls / hour"),
    ("assigned", "Assigned now"), ("due", "Follow-ups due"), ("overdue", "Overdue"),
    ("warm_hot", "Warm / hot"), ("appointments", "Booked now"), ("proposals", "Proposals"),
    ("won", "Wins"), ("lost", "Losses"), ("no_answer", "No answer"),
    ("voicemails", "Voicemails"), ("callbacks", "Callbacks"),
    ("created", "Leads created"), ("deleted", "Leads deleted"),
    ("searches", "Finder searches"), ("found", "Prospects found"),
    ("imports", "Files imported"), ("imported", "Rows imported"),
    ("logins", "Logins"), ("pages", "Pages visited"), ("lessons", "Training videos completed"),
    ("archived", "Archived leads"), ("needs_review", "Needs review"),
]


def date_window(params):
    today = timezone.localdate()
    period = params.get("period", "7d")
    if period not in {"today", "7d", "30d", "all", "custom"}:
        period = "7d"
    end = today
    start = today - timedelta(days={"today": 0, "7d": 6, "30d": 29}.get(period, 6))
    error = ""
    if period == "custom":
        try:
            start, end = parse_date(params.get("start", "")), parse_date(params.get("end", ""))
        except (ValueError, TypeError):
            start = end = None
        if not start or not end or start > end or end.year >= 9999:
            start, end, period = today - timedelta(days=6), today, "7d"
            error = "Choose a valid start and end date. Showing the last 7 days."
    if period == "all":
        start = None
    lower = timezone.make_aware(datetime.combine(start, time.min)) if start else None
    # End is inclusive for the user, exclusive for all database queries.
    upper = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min))
    query = {"period": period, "start": start.isoformat() if start else "", "end": end.isoformat()}
    return {**query, "lower": lower, "upper": upper, "error": error, "query": urlencode(query), "timezone": timezone.get_current_timezone_name()}


def during(qs, window, field="created_at"):
    qs = qs.filter(**{f"{field}__lt": window["upper"]})
    return qs.filter(**{f"{field}__gte": window["lower"]}) if window["lower"] else qs


def staff_queryset():
    return get_user_model().objects.filter(role__in=["employee", "admin"]).order_by("first_name", "username")


def performance_context(request, staff=None, *, filter_employees=True):
    window = date_window(request.GET)
    users = list(staff if staff is not None else staff_queryset())
    ids = [u.pk for u in users]
    by_id = {u.pk: {"employee": u, **{key: 0 for key, _ in COLUMNS}, "clocked_in": False, "last_activity": None} for u in users}
    events = during(EmployeeLeadEvent.objects.filter(actor_id__in=ids), window)
    for values in events.values("actor_id").annotate(
        calls=Count("id", filter=Q(counts_as_call=True)),
        worked=Count("lead_key", filter=Q(counts_as_call=True) | Q(assessment_booked=True), distinct=True),
        booked=Count("lead_key", filter=Q(assessment_booked=True), distinct=True),
        completed=Count("lead_key", filter=Q(assessment_completed=True), distinct=True),
        proposals=Count("lead_key", filter=Q(proposal=True), distinct=True),
        won=Count("lead_key", filter=Q(won=True), distinct=True),
        lost=Count("lead_key", filter=Q(lost=True), distinct=True),
        created=Count("id", filter=Q(kind="created")), deleted=Count("id", filter=Q(kind="deleted")),
        no_answer=Count("id", filter=Q(counts_as_call=True, status="no_answer")),
        voicemails=Count("id", filter=Q(counts_as_call=True, status="voicemail_left")),
        callbacks=Count("id", filter=Q(counts_as_call=True, status="callback_requested")),
    ):
        by_id[values.pop("actor_id")].update(values)
    today = timezone.localdate()
    for values in Lead.objects.filter(lead_type="internal_sales", assigned_to_id__in=ids).values("assigned_to_id").annotate(
        assigned=Count("id", filter=Q(archived=False)), archived_total=Count("id", filter=Q(archived=True)),
        due=Count("id", filter=Q(archived=False, follow_up_date__lte=today) & ~Q(status__in=CLOSED)),
        overdue=Count("id", filter=Q(archived=False, follow_up_date__lt=today) & ~Q(status__in=CLOSED)),
        warm_hot=Count("id", filter=Q(archived=False, lead_temperature__in=["warm", "hot"]) & ~Q(status__in=CLOSED)),
        appointments=Count("id", filter=Q(archived=False, status="appointment_scheduled", appointment_at__isnull=False)),
        needs_review=Count("id", filter=Q(archived=False, needs_review=True)),
    ):
        values["archived"] = values.pop("archived_total")
        by_id[values.pop("assigned_to_id")].update(values)
    for values in during(ActivityLog.objects.filter(actor_id__in=ids), window).values("actor_id").annotate(
        logins=Count("id", filter=Q(action="login")),
        pages=Count("id", filter=Q(action="request", method="GET", status_code=200) & ~Q(path__contains="/api/") & ~Q(path__contains="/media/")),
    ):
        by_id[values.pop("actor_id")].update(values)
    for values in EmployeeLeadEvent.objects.filter(actor_id__in=ids).values("actor_id").annotate(last_activity=Max("created_at")):
        by_id[values.pop("actor_id")].update(values)
    for values in ActivityLog.objects.filter(actor_id__in=ids).values("actor_id").annotate(last_activity=Max("created_at")):
        row = by_id[values.pop("actor_id")]
        row["last_activity"] = max(filter(None, [row["last_activity"], values["last_activity"]]))
    for values in during(LeadGenerationBatch.objects.filter(employee_id__in=ids), window).values("employee_id").annotate(searches=Count("id"), found=Sum("quantity_generated")):
        by_id[values.pop("employee_id")].update(values)
    for values in during(LeadImport.objects.filter(uploaded_by_id__in=ids), window).values("uploaded_by_id").annotate(imports=Count("id"), imported=Sum("imported_count")):
        by_id[values.pop("uploaded_by_id")].update(values)
    for values in during(EmployeeProgress.objects.filter(employee_id__in=ids, completed_at__isnull=False), window, "completed_at").values("employee_id").annotate(lessons=Count("version_id", distinct=True)):
        by_id[values.pop("employee_id")].update(values)
    now = timezone.now()
    # Clip shifts at the selected dates and at the automatic eight-hour shift limit.
    shifts = TimeClockEntry.objects.filter(employee_id__in=ids, clock_in__lt=window["upper"])
    if window["lower"]:
        shifts = shifts.filter(Q(clock_out__gte=window["lower"]) | Q(clock_out__isnull=True))
    for shift in shifts.only("employee_id", "clock_in", "clock_out"):
        row = by_id[shift.employee_id]
        end = min(shift.clock_out or min(now, shift.clock_in + timedelta(hours=8)), window["upper"], now)
        start = max(shift.clock_in, window["lower"]) if window["lower"] else shift.clock_in
        row["hours"] += max(0, (end - start).total_seconds()) / 3600
    open_ids = TimeClockEntry.objects.filter(employee_id__in=ids, clock_out__isnull=True, clock_in__gt=now-timedelta(hours=8)).values_list("employee_id", flat=True)
    for pk in open_ids:
        by_id[pk]["clocked_in"] = True
    rows = list(by_id.values())
    for row in rows:
        row["booking_rate"] = round(100 * row["booked"] / row["worked"], 1) if row["worked"] else 0
        row["calls_per_hour"] = round(row["calls"] / row["hours"], 1) if row["hours"] else 0
        row["hours"] = round(row["hours"], 2)
        row["cells"] = [{"key": key, "label": label, "value": row[key] or 0} for key, label in COLUMNS]
    sort = request.GET.get("metric_sort", "calls")
    if sort not in dict(COLUMNS):
        sort = "calls"
    rows.sort(key=lambda r: r[sort] or 0, reverse=True)
    query = request.GET.get("employee_q", "").strip()[:150]
    if query and filter_employees:
        rows = [r for r in rows if query.casefold() in f'{r["employee"].get_full_name()} {r["employee"].username} {r["employee"].email}'.casefold()]
    return {
        "employee_rows": rows, "metric_columns": [{"key": k, "label": v} for k, v in COLUMNS],
        "metric_window": window, "metric_sort": sort, "employee_q": query,
        "team_totals": {key: round(sum(r[key] or 0 for r in rows), 2) for key in ["calls", "booked", "hours", "overdue"]},
        "tracking_since": EmployeeLeadEvent.objects.order_by("created_at").values_list("created_at", flat=True).first(),
    }
