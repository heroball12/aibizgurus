from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import stripe
from clients.models import ClientAccount

stripe.api_key = settings.STRIPE_SECRET_KEY

PLAN_PRICE_MAP = {
    "starter": settings.STRIPE_PRICE_STARTER,
    "growth": settings.STRIPE_PRICE_GROWTH,
    "pro": settings.STRIPE_PRICE_PRO,
}


def _client_for_request(request):
    return request.user.client_accounts.order_by("-created_at").first()

@login_required
def billing_home(request):
    client = _client_for_request(request)
    if not client:
        messages.error(request, "A client account is required to access billing.")
        return redirect("owner_dashboard" if request.user.is_owner() else "ops_dashboard")
    return render(request, "billing/billing_home.html", {
        "client": client,
        "stripe_enabled": bool(settings.STRIPE_SECRET_KEY and not settings.STRIPE_SECRET_KEY.startswith("sk_test_placeholder")),
        "placeholder_mode": (not settings.STRIPE_SECRET_KEY) or settings.STRIPE_SECRET_KEY.startswith("sk_test_placeholder"),
    })

@login_required
def create_checkout_session(request, plan):
    client = _client_for_request(request)
    if not client:
        messages.error(request, "A client account is required to access billing.")
        return redirect("owner_dashboard" if request.user.is_owner() else "ops_dashboard")
    if plan not in PLAN_PRICE_MAP:
        messages.error(request, "Choose a valid plan.")
        return redirect("billing_home")
    if (not settings.STRIPE_SECRET_KEY) or settings.STRIPE_SECRET_KEY.startswith("sk_test_placeholder"):
        messages.info(request, "Stripe is in placeholder mode. Add real Stripe test/live keys to enable checkout.")
        return redirect("billing_home")
    price_id = PLAN_PRICE_MAP.get(plan)
    if (not price_id) or price_id.startswith("price_placeholder"):
        messages.info(request, "This Stripe price is still a placeholder. Add your real Stripe price ID to .env.")
        return redirect("billing_home")
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{settings.PUBLIC_BASE_URL}/billing/?success=1",
        cancel_url=f"{settings.PUBLIC_BASE_URL}/billing/?cancelled=1",
        client_reference_id=str(client.pk) if client else "",
        customer_email=client.contact_email if client else request.user.email,
    )
    return redirect(session.url)

@csrf_exempt
def stripe_webhook(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    webhook_secret = settings.STRIPE_WEBHOOK_SECRET
    if not webhook_secret:
        return JsonResponse({"received": True, "verified": False, "mode": "placeholder"})

    signature = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    try:
        event = stripe.Webhook.construct_event(request.body, signature, webhook_secret)
    except ValueError:
        return JsonResponse({"error": "Invalid Stripe payload"}, status=400)
    except stripe.error.SignatureVerificationError:
        return JsonResponse({"error": "Invalid Stripe signature"}, status=400)

    if event.get("type") == "checkout.session.completed":
        session = event["data"]["object"]
        client_id = session.get("client_reference_id")
        client = ClientAccount.objects.filter(pk=client_id).first() if client_id else None
        if client:
            client.activation_status = "active"
            client.save(update_fields=["activation_status"])

    return JsonResponse({"received": True, "verified": True})


@login_required
def payment_success(request):
    messages.success(request, "Payment received. Your account will be activated shortly.")
    return redirect("portal_home")
