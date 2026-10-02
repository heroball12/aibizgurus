import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode
from urllib import request as urlrequest

from django.conf import settings
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from core.permissions import employee_required
from core.security import decrypt_value, encrypt_value
from .models import (
    Lead,
    LeadActivity,
    OutreachMessage,
    SalesSMSContact,
    SalesSMSReply,
    StaffMailbox,
)
from .outreach import (
    make_draft,
    approve_and_send,
    message_data,
    mailbox_for,
    record_submission,
)
from .outreach_providers import (
    OutreachError,
    GMAIL_SCOPE,
    GOOGLE_SCOPES,
    google_ready,
    sms_ready,
    google_json,
    google_token,
    email_address,
    phone_number,
)
from .views import get_internal_lead_or_404, is_sales_manager


@employee_required
@never_cache
@require_GET
def connections(request):
    return render(
        request,
        "crm/outreach_connections.html",
        {
            "mailbox": mailbox_for(request.user),
            "google_ready": google_ready(),
            "sms_ready": sms_ready(),
            "sms_number": settings.SALES_SMS_FROM_NUMBER,
            "can_configure": is_sales_manager(request.user),
            "google_redirect": settings.SALES_GOOGLE_REDIRECT_URI,
            "sms_inbound_url": settings.PUBLIC_BASE_URL.rstrip("/")
            + reverse("outreach_sms_inbound"),
            "allowed_domains": ", ".join(settings.SALES_GOOGLE_DOMAINS),
        },
    )


@employee_required
@never_cache
@require_POST
def google_connect(request):
    if not google_ready():
        messages.error(
            request, "An owner needs to configure Google Workspace sending first."
        )
        return redirect("outreach_connections")
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    request.session["sales_google_oauth"] = {
        "state": state,
        "verifier": verifier,
        "at": time.time(),
        "user": request.user.pk,
    }
    params = {
        "client_id": settings.SALES_GOOGLE_CLIENT_ID,
        "redirect_uri": settings.SALES_GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "state": state,
        "access_type": "offline",
        "prompt": "consent select_account",
        "code_challenge": base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        )
        .decode()
        .rstrip("="),
        "code_challenge_method": "S256",
        "hd": settings.SALES_GOOGLE_DOMAINS[0],
    }
    return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@employee_required
@never_cache
@require_GET
@sensitive_variables("tokens", "profile", "refresh", "flow")
def google_callback(request):
    flow = request.session.pop("sales_google_oauth", {})
    try:
        if (
            not flow
            or flow.get("user") != request.user.pk
            or time.time() - flow.get("at", 0) > 600
            or not secrets.compare_digest(
                str(flow.get("state", "")), request.GET.get("state", "")
            )
        ):
            raise OutreachError(
                "That Google connection link expired or was already used. Please connect again."
            )
        if request.GET.get("error") or not request.GET.get("code"):
            raise OutreachError(
                "Google connection was cancelled. Nothing has been linked."
            )
        if not google_ready():
            raise OutreachError("Google sending is not configured.")
        tokens = google_token(
            {
                "grant_type": "authorization_code",
                "code": request.GET["code"],
                "redirect_uri": settings.SALES_GOOGLE_REDIRECT_URI,
                "code_verifier": flow["verifier"],
            }
        )
        if GMAIL_SCOPE not in str(tokens.get("scope", "")).split():
            raise OutreachError("Allow Gmail sending when connecting your mailbox.")
        access = tokens.get("access_token")
        if not isinstance(access, str) or not access:
            raise OutreachError(
                "Google did not provide an access token. Please reconnect."
            )
        profile = google_json(
            "https://openidconnect.googleapis.com/v1/userinfo", token=access
        )
        email = email_address(profile.get("email", "")).lower()
        subject = profile.get("sub")
        domains = {domain.lower() for domain in settings.SALES_GOOGLE_DOMAINS}
        if (
            profile.get("email_verified") is not True
            or str(profile.get("hd", "")).lower() not in domains
            or email.split("@")[-1] not in domains
            or not isinstance(subject, str)
            or not 1 <= len(subject) <= 255
        ):
            raise OutreachError(
                "Choose a verified company Google Workspace account from an allowed domain."
            )
        refresh = tokens.get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            raise OutreachError(
                "Google did not provide offline sending access. Remove the old grant in your Google account and reconnect."
            )
        with transaction.atomic():
            StaffMailbox.objects.update_or_create(
                user=request.user,
                defaults={
                    "email": email,
                    "google_subject": subject,
                    "refresh_token": encrypt_value(refresh),
                    "scopes": str(tokens["scope"]),
                    "active": True,
                },
            )
        messages.success(
            request,
            f"{email} is connected. You can now review and send emails from lead records.",
        )
    except IntegrityError:
        messages.error(
            request, "That mailbox is already connected to another employee."
        )
    except OutreachError as exc:
        messages.error(request, str(exc))
    response = redirect("outreach_connections")
    response["Referrer-Policy"] = "no-referrer"
    return response


@employee_required
@never_cache
@require_POST
@sensitive_variables("mailbox", "token")
def google_disconnect(request):
    mailbox = mailbox_for(request.user)
    revoked = True
    if mailbox:
        token = decrypt_value(mailbox.refresh_token)
        # Remove local access even if Google is temporarily unavailable.
        mailbox.delete()
        if token:
            try:
                req = urlrequest.Request(
                    "https://oauth2.googleapis.com/revoke",
                    data=urlencode({"token": token}).encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                with urlrequest.urlopen(req, timeout=10):
                    pass
            except Exception:
                revoked = False
    messages.success(request, "Your mailbox is disconnected from this site.")
    if not revoked:
        messages.warning(
            request,
            "Google did not confirm revocation. You can also remove this app under your Google account’s third-party connections.",
        )
    return redirect("outreach_connections")


def read_json(request):
    if len(request.body) > 30000:
        raise OutreachError("The message is too large.")
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise OutreachError(
            "Invalid request. Refresh this page and try again."
        ) from None
    if not isinstance(data, dict):
        raise OutreachError("Invalid request.")
    return data


@employee_required
@never_cache
@require_POST
@sensitive_post_parameters()
def draft(request, pk):
    lead = get_internal_lead_or_404(request.user, pk)
    try:
        data = read_json(request)
        message = make_draft(lead, request.user, data.get("channel"))
        return JsonResponse(message_data(message), status=201)
    except OutreachError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)


@employee_required
@never_cache
@require_POST
@sensitive_post_parameters()
def send(request, pk):
    message = get_object_or_404(OutreachMessage, pk=pk, employee=request.user)
    get_internal_lead_or_404(request.user, message.lead_id)
    try:
        message = approve_and_send(message.pk, request.user, read_json(request))
        return JsonResponse(message_data(message))
    except OutreachError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)


@employee_required
@never_cache
@require_GET
def status(request, pk):
    message = get_object_or_404(OutreachMessage, pk=pk, employee=request.user)
    get_internal_lead_or_404(request.user, message.lead_id)
    return JsonResponse(message_data(message))


def valid_twilio(request):
    from twilio.request_validator import RequestValidator

    if not sms_ready() or request.POST.get("AccountSid") != settings.TWILIO_ACCOUNT_SID:
        return False
    # Use the canonical public URL behind Render's reverse proxy; never trust Host headers.
    url = settings.PUBLIC_BASE_URL.rstrip("/") + request.get_full_path()
    return RequestValidator(settings.TWILIO_AUTH_TOKEN).validate(
        url, request.POST, request.headers.get("X-Twilio-Signature", "")
    )


@csrf_exempt
@require_POST
def sms_status(request, pk):
    if not valid_twilio(request):
        return HttpResponse(status=403)
    delivery = request.POST.get("MessageStatus", "")
    order = {
        "accepted": 0,
        "queued": 1,
        "sending": 2,
        "sent": 3,
        "failed": 4,
        "undelivered": 4,
        "delivered": 5,
    }
    if delivery not in order:
        return HttpResponse(status=204)
    with transaction.atomic():
        message = get_object_or_404(
            OutreachMessage.objects.select_for_update(), pk=pk, channel="sms"
        )
        sid = request.POST.get("MessageSid", "")
        if (
            message.status == "draft"
            or not sid
            or len(sid) > 120
            or request.POST.get("To") != message.recipient
            or request.POST.get("From") != message.sender
            or (message.provider_id and message.provider_id != sid)
        ):
            return HttpResponse(status=400)
        if order.get(message.delivery_status, -1) >= order[delivery]:
            return HttpResponse(status=204)
        message.provider_id, message.delivery_status, message.status = (
            sid,
            delivery,
            "sent",
        )
        message.sent_at = message.sent_at or timezone.now()
        message.error_message = (
            "The text could not be delivered. Check the number and SMS provider log."
            if delivery in {"failed", "undelivered"}
            else ""
        )
        record_submission(message)
        message.save()
        activity = message.activity
        activity.metadata = {**activity.metadata, "delivery_status": delivery}
        activity.save(update_fields=["metadata"])
        if request.POST.get("ErrorCode") == "21610":
            SalesSMSContact.objects.update_or_create(
                phone=message.recipient, defaults={"opted_out": True}
            )
    return HttpResponse(status=204)


@csrf_exempt
@require_POST
def sms_inbound(request):
    if not valid_twilio(request):
        return HttpResponse(status=403)
    if request.POST.get("To") != settings.SALES_SMS_FROM_NUMBER:
        return HttpResponse(status=400)
    sid, body = request.POST.get("MessageSid", ""), request.POST.get("Body", "")[:6000]
    try:
        phone = phone_number(request.POST.get("From", ""))
    except OutreachError:
        return HttpResponse(status=400)
    if not sid or len(sid) > 120:
        return HttpResponse(status=400)
    with transaction.atomic():
        _, created = SalesSMSReply.objects.get_or_create(
            provider_id=sid, defaults={"phone": phone, "body": body}
        )
        if created:
            opt_type = request.POST.get("OptOutType", "").upper()
            stopped = opt_type == "STOP" or body.strip().upper() in {
                "STOP",
                "STOPALL",
                "UNSUBSCRIBE",
                "CANCEL",
                "END",
                "QUIT",
                "REVOKE",
                "OPTOUT",
            }
            started = opt_type == "START" or body.strip().upper() in {"START", "UNSTOP"}
            if stopped or started:
                SalesSMSContact.objects.update_or_create(
                    phone=phone, defaults={"opted_out": stopped}
                )
            # Replies follow the most recent submitted conversation, never an unrelated client account.
            prior = (
                OutreachMessage.objects.filter(
                    channel="sms", recipient=phone, status="sent"
                )
                .order_by("-approved_at")
                .first()
            )
            if prior:
                lead = Lead.objects.select_for_update().get(pk=prior.lead_id)
                note = f"Text reply from {phone}:\n{body}"
                LeadActivity.objects.create(
                    lead=lead,
                    activity_type="sms",
                    raw_note=note,
                    cleaned_note=note,
                    inferred_status=lead.status,
                    classification_source="manual",
                    metadata={"direction": "inbound", "provider_id": sid},
                )
                if stopped:
                    lead.status = "do_not_contact"
                    lead.save(update_fields=["status"])
    return HttpResponse("<Response/>", content_type="text/xml")
