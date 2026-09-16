import hashlib
import json
import uuid
from datetime import timedelta

from django import forms
from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from core.forms import ConsultationRequestForm
from core.rate_limits import consume_budget, request_identity
from crm.models import Lead
from . import concierge
from .models import ConciergeCall, ConciergeSubmission


def owner_digest(request):
    if not request.session.session_key:
        request.session.create()
    return hashlib.sha256(request.session.session_key.encode()).hexdigest()


def body(request):
    try:
        if len(request.body) > 12_000:
            return None
        value = json.loads(request.body)
        return value if isinstance(value, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


def error(message, status=400):
    return JsonResponse({"error": message}, status=status)


@require_GET
@never_cache
@ensure_csrf_cookie
def concierge_home(request):
    directory = concierge.pages()
    initial = request.GET.get("page", "home")
    if initial not in directory or not directory[initial]["embedded"]:
        initial = "home"
    owner_digest(request)
    return render(request, "assistant_ai/concierge.html", {
        "config": {
            "available": concierge.is_available(), "pages": directory, "initialPage": initial,
            "startUrl": reverse("concierge_start"), "followupUrl": reverse("concierge_followup"),
            "maxSeconds": settings.VIDEO_CONCIERGE_MAX_SECONDS,
        },
        "available": concierge.is_available(), "directory": directory,
        "initial_path": directory[initial]["path"], "initial_label": directory[initial]["label"],
        "followup_form": FollowupForm(),
    })


@require_POST
@never_cache
def start_call(request):
    data = body(request)
    if not data or data.get("consent") is not True:
        return error("Please agree to start the live AI conversation.")
    if not concierge.is_available():
        return error("Live video is not available yet. You can still browse services, schedule a consultation or request help below.", 503)
    owner = owner_digest(request)
    now = timezone.now()
    try:
        with transaction.atomic():
            ConciergeCall.objects.filter(owner_digest=owner, active=True, created_at__lt=now-timedelta(minutes=10)).update(active=False, status="expired")
            if ConciergeCall.objects.filter(owner_digest=owner, active=True).exists():
                existing = ConciergeCall.objects.get(owner_digest=owner, active=True)
                return JsonResponse({"error":"A video call is already open in this browser. Use End call to close it before starting another.", "existingCall":{"id":str(existing.pk),"stopUrl":reverse("concierge_stop",args=[existing.pk])}}, status=409)
            if not consume_budget("concierge-start", request_identity(request), limit=settings.VIDEO_CONCIERGE_HOURLY_LIMIT, window=3600):
                return error("You’ve reached the video call limit for now. You can still book or send a request.", 429)
            if not consume_budget("concierge-daily", "platform", limit=settings.VIDEO_CONCIERGE_DAILY_LIMIT, window=86400):
                return error("Live video is at capacity today. Please use the consultation calendar or send a request.", 429)
            call = ConciergeCall.objects.create(owner_digest=owner)
    except IntegrityError:
        return error("A video call is already being started. Please wait.", 409)
    try:
        result = concierge.create_session(data.get("page", "home"))
        provider_id = uuid.UUID(str(result.get("id", "")))
    except (concierge.RunwayError, ValueError, AttributeError):
        call.status, call.active = "failed", False
        call.save(update_fields=["status", "active"])
        return error("The live video connection could not start. Please try again or request a follow-up.", 502)
    call.provider_id, call.status = provider_id, "pending"
    call.save(update_fields=["provider_id", "status"])
    return JsonResponse({"id": str(call.id), "status": "pending", "textUrl":reverse("concierge_text",args=[call.id]), "pollUrl": reverse("concierge_poll", args=[call.id]), "stopUrl": reverse("concierge_stop", args=[call.id])}, status=201)


def owned_call(request, call_id):
    return get_object_or_404(ConciergeCall, id=call_id, owner_digest=owner_digest(request))


@require_POST
@never_cache
def poll_call(request, call_id):
    call = owned_call(request, call_id)
    if not call.active or call.status != "pending":
        return error("This call is no longer waiting to connect. Start a new call.", 409)
    if not consume_budget("concierge-poll", str(call.id), limit=70, window=300):
        return error("The video connection took too long. End this call and try again.", 429)
    try:
        result = concierge.runway_request("GET", f"/realtime_sessions/{call.provider_id}")
    except concierge.RunwayError as exc:
        return error(str(exc), 502)
    status = result.get("status")
    if status == "READY" and isinstance(result.get("sessionKey"), str) and result["sessionKey"]:
        # Only one caller can claim this session's short-lived connection key.
        claimed = ConciergeCall.objects.filter(pk=call.pk, active=True, status="pending").update(status="issued")
        if not claimed:
            return error("This call has already connected or ended.", 409)
        return JsonResponse({"status": "ready", "credentials": {"sessionId": str(call.provider_id), "sessionKey": result["sessionKey"]}})
    if status in {"FAILED", "CANCELED", "CANCELLED", "COMPLETED", "ENDED", "EXPIRED"}:
        ConciergeCall.objects.filter(pk=call.pk).update(status="ended", active=False)
        return error("The video session ended before connecting. Please try again.", 502)
    if timezone.now()-call.created_at > timedelta(seconds=120):
        return error("The video connection took too long. End this call and try again.", 504)
    return JsonResponse({"status": "pending"})


@require_POST
@never_cache
def stop_call(request, call_id):
    call = owned_call(request, call_id)
    if not call.active:
        return JsonResponse({"status": "ended"})
    ConciergeCall.objects.filter(pk=call.pk).update(status="ending")
    try:
        concierge.runway_request("DELETE", f"/realtime_sessions/{call.provider_id}")
    except concierge.RunwayError as exc:
        try:
            remote = concierge.runway_request("GET", f"/realtime_sessions/{call.provider_id}")
        except concierge.RunwayError:
            return error(str(exc), 502)
        if remote.get("status") not in {"COMPLETED", "FAILED", "CANCELED", "CANCELLED", "ENDED", "EXPIRED"}:
            return error(str(exc), 502)
    ConciergeCall.objects.filter(pk=call.pk).update(active=False, status="ended")
    return JsonResponse({"status": "ended"})


class FollowupForm(ConsultationRequestForm):
    message = forms.CharField(required=False, max_length=4000, label="Growth goal or support request", widget=forms.Textarea(attrs={"rows":4}))
    consent = forms.BooleanField(label="Send these details to AI Business Gurus so the team can contact me about this request.")
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["message"].max_length = 4000
        self.fields["message"].widget.attrs["maxlength"] = 4000
        self.fields["message"].label = "Growth goal or support request"
        for field in self.fields.values():
            if getattr(field, "max_length", None):
                field.widget.attrs["maxlength"] = field.max_length


@require_POST
@never_cache
def submit_followup(request):
    form = FollowupForm(request.POST)
    if not form.is_valid() or request.POST.get("website"):
        return JsonResponse({"error": "Please check the form and confirm you want us to contact you.", "fields": form.errors.get_json_data()}, status=400)
    try:
        submission_id = uuid.UUID(request.POST.get("submission_id", ""))
    except ValueError:
        return error("Please refresh and try again.")
    owner = owner_digest(request)
    existing = ConciergeSubmission.objects.filter(pk=submission_id, owner_digest=owner).first()
    if existing:
        return JsonResponse({"sent": True, "reference": existing.consultation_id})
    try:
        with transaction.atomic():
            if not consume_budget("consultation", request_identity(request), limit=5, window=3600):
                return error("Too many requests. Please try again later or use the consultation calendar.", 429)
            obj = form.save()
            ConciergeSubmission.objects.create(id=submission_id, owner_digest=owner, consultation=obj)
            Lead.objects.create(lead_type="internal_sales", name=obj.name, email=obj.email, phone=obj.phone,
                business_name=obj.business_name, industry=obj.industry, source="Video concierge follow-up",
                status="new", notes=obj.message)
    except IntegrityError:
        existing = ConciergeSubmission.objects.filter(pk=submission_id, owner_digest=owner).first()
        if not existing:
            return error("Please refresh and try again.", 409)
        obj = existing.consultation
    return JsonResponse({"sent": True, "reference": obj.pk})


@require_POST
@never_cache
def text_input(request, call_id):
    """Turn typed input into speech for Runway's native voice-only Character."""
    from django.core import signing
    call = owned_call(request, call_id)
    if not call.active or call.status != "issued":
        return error("Start a live conversation before sending a message.", 409)
    data = body(request)
    text = data.get("message") if data else None
    if not isinstance(text, str) or not text.strip() or len(text) > 500:
        return error("Please enter a message of 500 characters or fewer.")
    if not consume_budget("concierge-text", str(call.id), limit=12, window=600):
        return error("This call has reached its typed message limit. You can use your mic or request a follow-up.", 429)
    if not consume_budget("concierge-text-daily", "platform", limit=settings.VIDEO_CONCIERGE_DAILY_LIMIT * 12, window=86400):
        return error("Typed conversations are at capacity. Please use your mic or request a follow-up.", 429)
    try:
        result = concierge.runway_request("POST", "/text_to_speech", {
            "model":"eleven_multilingual_v2", "promptText":text.strip(),
            "voice":{"type":"runway-preset", "presetId":"Maya"},
        })
        task_id = str(uuid.UUID(result["id"]))
    except (concierge.RunwayError, KeyError, ValueError, TypeError):
        return error("Your message could not be prepared. Please try again or use your microphone.", 502)
    token = signing.dumps({"call":str(call.pk), "task":task_id}, salt="concierge-typed-input")
    return JsonResponse({"token":token, "pollUrl":reverse("concierge_text_status",args=[call.pk])}, status=201)


@require_POST
@never_cache
def text_status(request, call_id):
    from django.core import signing
    from django.http import HttpResponse
    call = owned_call(request, call_id)
    if not call.active or call.status != "issued":
        return error("This video conversation has ended.", 409)
    data = body(request)
    try:
        task = signing.loads(data.get("token", "") if data else "", salt="concierge-typed-input", max_age=120)
        if task["call"] != str(call.pk):
            raise ValueError
        task_id = str(uuid.UUID(task["task"]))
    except (signing.BadSignature, ValueError, KeyError, TypeError):
        return error("That message has expired. Please send it again.", 400)
    if not consume_budget("concierge-text-poll", task_id, limit=45, window=300):
        return error("That message took too long. Please try again.", 429)
    try:
        result = concierge.runway_request("GET", "/tasks/"+task_id)
        if result.get("status") == "SUCCEEDED":
            output = result.get("output", [])
            if not isinstance(output, list) or not output or not isinstance(output[0],str):
                raise concierge.RunwayError
            audio = concierge.fetch_speech_audio(output[0])
            return HttpResponse(audio, content_type="audio/mpeg")
        if result.get("status") in {"FAILED", "CANCELED", "CANCELLED"}:
            raise concierge.RunwayError
    except concierge.RunwayError:
        return error("Your message could not be delivered. Please try again or use your microphone.", 502)
    return JsonResponse({"status":"pending"}, status=202)
