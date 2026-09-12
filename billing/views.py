import logging
from datetime import datetime, timezone as dt_timezone
from uuid import uuid4

import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from clients.models import ClientAccount
from .models import BillingCustomer, BillingEvent

logger = logging.getLogger(__name__)
PLANS = {"starter": "Starter", "growth": "Growth", "pro": "AI Workforce"}


def _configured(value):
    return bool(value and "placeholder" not in value)


def _price_map():
    return {plan: getattr(settings, f"STRIPE_PRICE_{plan.upper()}", "") for plan in PLANS}


def _client_for_request(request):
    return request.user.client_accounts.order_by("-created_at").first()


def _object_id(value):
    return value.get("id", "") if isinstance(value, dict) else value or ""


def _find_client(obj, client_id=None):
    candidate = client_id or (obj.get("metadata") or {}).get("client_id")
    if candidate and str(candidate).isdigit():
        client = ClientAccount.objects.filter(pk=candidate).first()
        if client:
            return client
    customer_id = _object_id(obj.get("customer"))
    if customer_id:
        billing = BillingCustomer.objects.filter(stripe_customer_id=customer_id).select_related("client").first()
        if billing:
            return billing.client
    return None


def _sync_subscription(subscription_id, client=None):
    """Read Stripe's current state so delayed/reordered events cannot restore stale access."""
    subscription = stripe.Subscription.retrieve(subscription_id, api_key=settings.STRIPE_SECRET_KEY)
    client = client or _find_client(subscription)
    if not client:
        sessions = stripe.checkout.Session.list(subscription=subscription_id, limit=10, api_key=settings.STRIPE_SECRET_KEY)
        for session in sessions.get("data", []):
            if session.get("status") == "complete":
                client = _find_client(session, session.get("client_reference_id"))
                if client:
                    break
    if not client:
        return False
    with transaction.atomic():
        client = ClientAccount.objects.select_for_update().get(pk=client.pk)
        billing, _ = BillingCustomer.objects.get_or_create(client=client)
        # Serialize retrieval with access changes to prevent racing deliveries.
        subscription = stripe.Subscription.retrieve(subscription_id, api_key=settings.STRIPE_SECRET_KEY)
        if billing.stripe_subscription_id and billing.stripe_subscription_id != subscription_id:
            # An old subscription must not overwrite the replacement subscription.
            if subscription.get("status") not in {"active", "trialing"}:
                return False
            if billing.status in {"active", "trialing"}:
                logger.warning("Multiple subscriptions for client %s require billing review", client.pk)
                return False
        billing.stripe_customer_id = _object_id(subscription.get("customer"))
        billing.stripe_subscription_id = subscription_id
        billing.status = subscription.get("status", "incomplete")
        items = (subscription.get("items") or {}).get("data", [])
        plan = (subscription.get("metadata") or {}).get("plan")
        for item in items:
            price_id = _object_id(item.get("price"))
            plan = next((key for key, value in _price_map().items() if value and value == price_id), plan)
        billing.plan = plan if plan in PLANS else client.plan
        end = subscription.get("current_period_end") or max((item.get("current_period_end", 0) for item in items), default=0)
        billing.current_period_end = datetime.fromtimestamp(end, tz=dt_timezone.utc) if end else None
        billing.save()
        client.plan = billing.plan
        client.paid_until = billing.current_period_end
        if billing.status in {"active", "trialing"}:
            client.activation_status, client.status = "active", "active"
        elif billing.status in {"canceled", "incomplete_expired"}:
            client.activation_status, client.status = "cancelled", "cancelled"
        elif billing.status in {"past_due", "unpaid", "paused"}:
            client.activation_status, client.status = "paused", "paused"
        else:
            client.activation_status = "pending_payment"
        client.save(update_fields=["plan", "paid_until", "activation_status", "status"])
    return True


@login_required
def billing_home(request):
    client = _client_for_request(request)
    if not client:
        messages.error(request, "A client account is required to access billing.")
        return redirect("owner_dashboard" if request.user.is_owner() else "ops_dashboard")
    customer = BillingCustomer.objects.filter(client=client).first()
    return render(request, "billing/billing_home.html", {
        "client": client, "billing_customer": customer,
        "stripe_enabled": _configured(settings.STRIPE_SECRET_KEY),
        "plans": [{"key": key, "name": name, "available": _configured(settings.STRIPE_SECRET_KEY) and _configured(_price_map()[key])} for key, name in PLANS.items()],
    })


@login_required
@require_POST
def create_checkout_session(request, plan):
    client = _client_for_request(request)
    if not client or plan not in PLANS:
        return redirect("billing_home")
    customer = BillingCustomer.objects.filter(client=client).first()
    if customer and customer.stripe_subscription_id and customer.status not in {"canceled", "incomplete_expired", "inactive"}:
        messages.info(request, "Manage your existing subscription below to avoid a duplicate subscription.")
        return redirect("billing_home")
    if client.is_paid_active:
        messages.info(request, "Your account is active. Contact us to change your plan.")
        return redirect("billing_home")
    if not _configured(settings.STRIPE_SECRET_KEY) or not _configured(_price_map()[plan]):
        messages.info(request, "Online checkout for this plan is not available yet. Please contact us to arrange activation.")
        return redirect("billing_home")
    line_items = [{"price": _price_map()[plan], "quantity": 1}]
    setup_price = getattr(settings, f"STRIPE_SETUP_PRICE_{plan.upper()}", "")
    if _configured(setup_price):
        line_items.append({"price": setup_price, "quantity": 1})
    metadata = {"client_id": str(client.pk), "plan": plan}
    # Reuse a recent in-progress Checkout Session for duplicate button clicks.
    checkout_key = f"billing_checkout_{client.pk}_{plan}"
    nonce = request.session.get(checkout_key) or str(uuid4())
    request.session[checkout_key] = nonce
    kwargs = {"customer": customer.stripe_customer_id} if customer and customer.stripe_customer_id else {"customer_email": client.contact_email or request.user.email}
    try:
        session = stripe.checkout.Session.create(
            mode="subscription", line_items=line_items,
            success_url=f"{settings.PUBLIC_BASE_URL}{reverse('payment_success')}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.PUBLIC_BASE_URL}{reverse('billing_home')}?cancelled=1",
            client_reference_id=str(client.pk), metadata=metadata, subscription_data={"metadata": metadata},
            api_key=settings.STRIPE_SECRET_KEY, idempotency_key=f"checkout-{client.pk}-{plan}-{nonce}", **kwargs,
        )
        if session.get("status") == "complete":
            from urllib.parse import urlencode
            return redirect(reverse("payment_success") + "?" + urlencode({"session_id": session["id"]}))
        if session.get("status") == "expired":
            request.session.pop(checkout_key, None)
            messages.info(request, "Your previous checkout expired. Select the plan again to open a fresh checkout.")
            return redirect("billing_home")
        return redirect(session.url)
    except stripe.error.StripeError:
        logger.exception("Stripe checkout failed for client %s", client.pk)
        request.session.pop(checkout_key, None)
        messages.error(request, "Checkout could not be opened. Please try again or contact us for help.")
        return redirect("billing_home")


@login_required
@require_POST
def customer_portal(request):
    client = _client_for_request(request)
    customer = BillingCustomer.objects.filter(client=client).first() if client else None
    if not customer or not customer.stripe_customer_id or not _configured(settings.STRIPE_SECRET_KEY):
        messages.info(request, "Contact us for help with your subscription.")
        return redirect("billing_home")
    try:
        session = stripe.billing_portal.Session.create(customer=customer.stripe_customer_id, return_url=f"{settings.PUBLIC_BASE_URL}{reverse('billing_home')}", api_key=settings.STRIPE_SECRET_KEY)
        return redirect(session.url)
    except stripe.error.StripeError:
        logger.exception("Stripe portal failed for client %s", client.pk)
        messages.error(request, "Billing management is temporarily unavailable. Please contact us for help.")
        return redirect("billing_home")


def _process_event(event):
    kind = event["type"]
    obj = event["data"]["object"]
    if kind.startswith("customer.subscription."):
        return _sync_subscription(obj["id"])
    if kind in {"checkout.session.completed", "checkout.session.async_payment_succeeded", "checkout.session.async_payment_failed"}:
        if obj.get("mode") != "subscription":
            return False
        client = _find_client(obj, obj.get("client_reference_id"))
        subscription_id = _object_id(obj.get("subscription"))
        if client and subscription_id:
            return _sync_subscription(subscription_id, client)
    if kind in {"invoice.paid", "invoice.payment_failed", "invoice.payment_action_required"}:
        subscription_id = _object_id(obj.get("subscription") or ((obj.get("parent") or {}).get("subscription_details") or {}).get("subscription"))
        if subscription_id:
            return _sync_subscription(subscription_id, _find_client(obj))
    return False


@csrf_exempt
@require_POST
def stripe_webhook(request):
    if not settings.STRIPE_WEBHOOK_SECRET:
        return JsonResponse({"error": "Billing webhook is not configured."}, status=503)
    try:
        event = stripe.Webhook.construct_event(request.body, request.META.get("HTTP_STRIPE_SIGNATURE", ""), settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        return JsonResponse({"error": "Invalid Stripe signature or payload"}, status=400)
    if not _configured(settings.STRIPE_SECRET_KEY):
        return JsonResponse({"error": "Billing synchronization is not configured."}, status=503)
    if not event.get("id") or not event.get("type"):
        return JsonResponse({"error": "Invalid Stripe event"}, status=400)
    try:
        with transaction.atomic():
            receipt, created = BillingEvent.objects.get_or_create(event_id=event["id"], defaults={"event_type": event["type"]})
            if created:
                _process_event(event)
        return JsonResponse({"received": True, "verified": True})
    except stripe.error.StripeError:
        logger.exception("Stripe synchronization failed for event %s", event["id"])
        return JsonResponse({"error": "Subscription synchronization failed; retry required."}, status=503)


@login_required
def payment_success(request):
    client = _client_for_request(request)
    session_id = request.GET.get("session_id", "")
    if client and session_id and _configured(settings.STRIPE_SECRET_KEY):
        try:
            session = stripe.checkout.Session.retrieve(session_id, api_key=settings.STRIPE_SECRET_KEY)
            if session.get("client_reference_id") == str(client.pk) and session.get("mode") == "subscription" and session.get("subscription"):
                _sync_subscription(_object_id(session["subscription"]), client)
                client.refresh_from_db()
                if client.is_paid_active:
                    for key in list(request.session.keys()):
                        if key.startswith(f"billing_checkout_{client.pk}_"):
                            request.session.pop(key, None)
                    messages.success(request, "Your subscription is confirmed and your account is active.")
                    return redirect("portal_home")
        except stripe.error.StripeError:
            logger.warning("Checkout verification unavailable for client %s", client.pk)
    messages.info(request, "We are waiting for payment confirmation. Your account status will update after verification.")
    return redirect("billing_home")
