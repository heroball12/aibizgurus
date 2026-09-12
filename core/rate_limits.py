import hashlib
import ipaddress
from django.conf import settings
import time
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import RequestBudget


def consume_budget(scope, identity, *, limit, window=60):
    """Atomically reserve one request in a fixed window shared by all workers."""
    now = timezone.now()
    slot = int(time.time()) // window
    key = hashlib.sha256(f"{scope}:{identity}:{slot}".encode()).hexdigest()
    with transaction.atomic():
        RequestBudget.objects.get_or_create(key=key, defaults={"expires_at": now + timedelta(seconds=window * 2)})
        budget = RequestBudget.objects.select_for_update().get(pk=key)
        if budget.count >= limit:
            return False
        budget.count += 1
        budget.save(update_fields=["count"])
    # Indexed cleanup keeps the table bounded without a separate scheduled job.
    RequestBudget.objects.filter(expires_at__lt=now).delete()
    return True


def request_identity(request):
    hops = getattr(settings, "TRUSTED_PROXY_HOPS", 0)
    if hops > 0:
        chain = [value.strip() for value in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if value.strip()]
        if len(chain) >= hops:
            try:
                return str(ipaddress.ip_address(chain[-hops]))
            except ValueError:
                pass
    return request.META.get("REMOTE_ADDR", "unknown")
