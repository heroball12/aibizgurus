from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import render
from core.permissions import owner_required
from clients.models import ClientAccount, AIInstance
from crm.models import Lead
from .models import ActivityLog
from .utils import activity_table_exists

User = get_user_model()

@owner_required
def owner_dashboard(request):
    audit_ready = activity_table_exists()
    logs = ActivityLog.objects.select_related("actor").order_by("-created_at")[:50] if audit_ready else ActivityLog.objects.none()
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

    return render(request, "audit/activity_logs.html", {"logs": logs[:500], "audit_ready": audit_ready})

@owner_required
def owner_users(request):
    users = User.objects.order_by("role", "username")
    return render(request, "audit/owner_users.html", {"users": users})

@owner_required
def owner_clients(request):
    clients = ClientAccount.objects.order_by("-created_at")
    return render(request, "audit/owner_clients.html", {"clients": clients})
