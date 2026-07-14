import time

from django.db import connection, transaction
from .models import ActivityLog

_ACTIVITY_TABLE_EXISTS = None
_ACTIVITY_TABLE_CHECKED_AT = 0
_ACTIVITY_TABLE_CACHE_SECONDS = 60


def get_client_ip(request):
    if not request:
        return None
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")

def safe_user_data(user):
    if not user or not getattr(user, "is_authenticated", False):
        return None, "", ""
    return user, getattr(user, "username", "") or "", getattr(user, "role", "") or ""

def activity_table_exists():
    global _ACTIVITY_TABLE_EXISTS, _ACTIVITY_TABLE_CHECKED_AT
    now = time.monotonic()
    if (
        _ACTIVITY_TABLE_EXISTS is not None
        and now - _ACTIVITY_TABLE_CHECKED_AT < _ACTIVITY_TABLE_CACHE_SECONDS
    ):
        return _ACTIVITY_TABLE_EXISTS
    try:
        _ACTIVITY_TABLE_EXISTS = ActivityLog._meta.db_table in connection.introspection.table_names()
    except Exception:
        _ACTIVITY_TABLE_EXISTS = False
    _ACTIVITY_TABLE_CHECKED_AT = now
    return _ACTIVITY_TABLE_EXISTS

def log_activity(*, user=None, request=None, action="other", message="", model_label="", object_id="", object_repr="", metadata=None, status_code=None):
    if not activity_table_exists():
        return None

    actor, username, role = safe_user_data(user)
    path = getattr(request, "path", "") if request else ""
    method = getattr(request, "method", "") if request else ""
    ip = get_client_ip(request) if request else None
    ua = request.META.get("HTTP_USER_AGENT", "") if request else ""

    try:
        # The savepoint prevents an audit insert failure from poisoning an outer
        # admin transaction. Logging is always best-effort.
        with transaction.atomic():
            return ActivityLog.objects.create(
                actor=actor,
                actor_username=username,
                actor_role=role,
                action=action,
                path=path[:500],
                method=method[:20],
                status_code=status_code,
                ip_address=ip,
                user_agent=ua,
                model_label=model_label[:120],
                object_id=str(object_id or "")[:120],
                object_repr=str(object_repr or "")[:300],
                message=message,
                metadata=metadata or {},
            )
    except Exception:
        return None
