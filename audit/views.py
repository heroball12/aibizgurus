from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from core.permissions import owner_required
from clients.models import ClientAccount, AIInstance
from crm.models import Lead, LeadActivity, LeadImport
from crm.views import apply_lead_filters, lead_filter_context, lead_filter_values, order_leads
from .forms import StaffUserForm
from .models import ActivityLog, TimeClockEntry
from .utils import activity_table_exists, log_activity

User = get_user_model()


def paginate(request, queryset, per_page=100):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def staff_admin_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        allowed = request.user.is_superuser or getattr(request.user, "role", "") in {"admin", "owner"}
        if not allowed:
            messages.error(request, "Admin access required.")
            return redirect("ops_dashboard" if request.user.is_employee_or_admin() else "portal_home")
        return view_func(request, *args, **kwargs)
    return wrapper

@owner_required
def owner_dashboard(request):
    audit_ready = activity_table_exists()
    logs = (
        ActivityLog.objects.select_related("actor")
        .only("actor", "actor_username", "actor_role", "action", "path", "message", "status_code", "created_at", "object_repr")
        .order_by("-created_at")[:50]
        if audit_ready
        else ActivityLog.objects.none()
    )
    context = {
        "user_count": User.objects.count(),
        "ops_count": User.objects.filter(role__in=["employee", "admin", "owner"]).count(),
        "client_count": ClientAccount.objects.count(),
        "assistant_count": AIInstance.objects.count(),
        "internal_lead_count": Lead.objects.filter(lead_type="internal_sales").count(),
        "client_lead_count": Lead.objects.filter(lead_type="client_customer").count(),
        "logs": logs,
        "audit_ready": audit_ready,
    }
    return render(request, "audit/owner_dashboard.html", context)

@owner_required
def owner_activity_logs(request):
    audit_ready = activity_table_exists()
    logs = ActivityLog.objects.select_related("actor").order_by("-created_at") if audit_ready else ActivityLog.objects.none()
    actor = request.GET.get("actor", "").strip()
    action = request.GET.get("action", "").strip()
    role = request.GET.get("role", "").strip()
    q = request.GET.get("q", "").strip()

    if actor:
        logs = logs.filter(actor_username__icontains=actor)
    if action:
        logs = logs.filter(action=action)
    if role:
        logs = logs.filter(actor_role=role)
    if q:
        logs = logs.filter(Q(message__icontains=q) | Q(path__icontains=q) | Q(object_repr__icontains=q))

    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(request, "audit/activity_logs.html", {
        "page_obj": paginate(request, logs, 100),
        "audit_ready": audit_ready,
        "query_string": query_params.urlencode(),
    })

@owner_required
def owner_users(request):
    users = User.objects.only("username", "email", "role", "is_staff", "is_superuser").order_by("role", "username")
    return render(request, "audit/owner_users.html", {"page_obj": paginate(request, users, 100)})

@owner_required
def owner_clients(request):
    clients = ClientAccount.objects.select_related("user").order_by("-created_at")
    return render(request, "audit/owner_clients.html", {"page_obj": paginate(request, clients, 100)})


@staff_admin_required
def staff_users(request):
    staff = User.objects.filter(role__in=["employee", "admin"]).only(
        "username", "email", "first_name", "last_name", "role", "is_active", "is_staff"
    ).order_by("role", "first_name", "username")
    return render(request, "audit/staff_users.html", {"staff_users": staff})


@staff_admin_required
def staff_performance(request, pk):
    staff_user = get_object_or_404(User, pk=pk, role__in=["employee", "admin"])
    leads = Lead.objects.filter(lead_type="internal_sales", archived=False, assigned_to=staff_user)
    filters = lead_filter_values(request)
    filtered_leads = order_leads(apply_lead_filters(leads, filters), filters["sort"])
    today = timezone.localdate()
    closed_statuses = ["closed_won", "closed_lost", "not_interested", "do_not_contact", "permanently_closed"]
    data = leads.aggregate(
        total=Count("id"),
        worked=Count("id", filter=~Q(notes="") | ~Q(cleaned_notes="")),
        warm=Count("id", filter=Q(lead_temperature="warm")),
        hot=Count("id", filter=Q(lead_temperature="hot")),
        cold=Count("id", filter=Q(lead_temperature="cold")),
        closed=Count("id", filter=Q(lead_temperature="closed")),
        followups_due=Count(
            "id",
            filter=(Q(follow_up_date__lte=today) | Q(status__in=["callback_requested", "follow_up", "email_requested", "information_requested"]))
            & ~Q(status__in=closed_statuses),
        ),
        overdue=Count("id", filter=Q(follow_up_date__lt=today) & ~Q(status__in=closed_statuses)),
        callbacks=Count("id", filter=Q(status="callback_requested")),
        emails=Count("id", filter=Q(status="email_requested")),
        info_requested=Count("id", filter=Q(status="information_requested")),
        appointments=Count("id", filter=Q(status__in=["appointment_scheduled", "appointment_completed"])),
        proposals=Count("id", filter=Q(status__in=["proposal_requested", "proposal_sent"])),
        closed_won=Count("id", filter=Q(status="closed_won")),
        closed_lost=Count("id", filter=Q(status="closed_lost")),
        needs_review=Count("id", filter=Q(needs_review=True)),
    )
    total = data["total"] or 0
    worked = data["worked"] or 0
    performance = {
        **{key: value or 0 for key, value in data.items()},
        "contact_rate": round((worked / total) * 100) if total else 0,
        "warm_hot": (data["warm"] or 0) + (data["hot"] or 0),
        "close_rate": round(((data["closed_won"] or 0) / total) * 100) if total else 0,
    }
    status_labels = dict(Lead.STATUS_CHOICES)
    temperature_labels = dict(Lead._meta.get_field("lead_temperature").choices)
    status_breakdown = [
        {"status": row["status"], "label": status_labels.get(row["status"], row["status"]), "count": row["count"]}
        for row in leads.values("status").annotate(count=Count("id")).order_by("-count", "status")
    ]
    temperature_breakdown = [
        {"temperature": row["lead_temperature"], "label": temperature_labels.get(row["lead_temperature"], row["lead_temperature"]), "count": row["count"]}
        for row in leads.values("lead_temperature").annotate(count=Count("id")).order_by("-count", "lead_temperature")
    ]
    recent_activities = (
        LeadActivity.objects.filter(Q(user=staff_user) | Q(lead__assigned_to=staff_user), lead__lead_type="internal_sales")
        .select_related("lead")
        .order_by("-created_at")[:20]
    )
    recent_imports = LeadImport.objects.filter(uploaded_by=staff_user).order_by("-created_at")[:10]
    open_time_entry = TimeClockEntry.objects.filter(employee=staff_user, clock_out__isnull=True).order_by("-clock_in").first()
    recent_time_entries = TimeClockEntry.objects.filter(employee=staff_user).order_by("-clock_in")[:10]
    week_start = timezone.now() - timedelta(days=7)
    weekly_hours = sum(
        entry.duration_hours
        for entry in TimeClockEntry.objects.filter(employee=staff_user, clock_in__gte=week_start, clock_out__isnull=False)
    )
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(request, "audit/staff_performance.html", {
        "staff_user": staff_user,
        "performance": performance,
        "status_breakdown": status_breakdown,
        "temperature_breakdown": temperature_breakdown,
        "recent_activities": recent_activities,
        "recent_imports": recent_imports,
        "open_time_entry": open_time_entry,
        "recent_time_entries": recent_time_entries,
        "weekly_hours": round(weekly_hours, 2),
        "page_obj": paginate(request, filtered_leads.select_related("assigned_to"), 50),
        "filtered_count": filtered_leads.count(),
        "query_string": query_params.urlencode(),
        **lead_filter_context(request, leads),
    })


@staff_admin_required
def staff_user_create(request):
    if request.method == "POST":
        form = StaffUserForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_activity(
                user=request.user,
                request=request,
                action="create",
                model_label="accounts.User",
                object_id=user.pk,
                object_repr=user.username,
                message="Created staff user.",
            )
            messages.success(request, f"Staff account created for {user.get_full_name() or user.username}.")
            return redirect("staff_users")
    else:
        form = StaffUserForm(initial={"role": "employee", "is_active": True, "password": "AIBG123"})
    return render(request, "audit/staff_user_form.html", {"form": form, "staff_user": None})


@staff_admin_required
def staff_user_edit(request, pk):
    staff_user = get_object_or_404(User, pk=pk, role__in=["employee", "admin"])
    if request.method == "POST":
        form = StaffUserForm(request.POST, instance=staff_user)
        if form.is_valid():
            user = form.save()
            log_activity(
                user=request.user,
                request=request,
                action="update",
                model_label="accounts.User",
                object_id=user.pk,
                object_repr=user.username,
                message="Updated staff user.",
            )
            messages.success(request, "Staff account updated.")
            return redirect("staff_users")
    else:
        form = StaffUserForm(instance=staff_user)
    return render(request, "audit/staff_user_form.html", {"form": form, "staff_user": staff_user})


@staff_admin_required
def staff_user_deactivate(request, pk):
    staff_user = get_object_or_404(User, pk=pk, role__in=["employee", "admin"])
    if request.method == "POST":
        staff_user.is_active = False
        staff_user.save(update_fields=["is_active"])
        log_activity(
            user=request.user,
            request=request,
            action="update",
            model_label="accounts.User",
            object_id=staff_user.pk,
            object_repr=staff_user.username,
            message="Deactivated staff user.",
        )
        messages.success(request, f"{staff_user.username} was deactivated.")
    return redirect("staff_users")
