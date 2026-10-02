import json
import logging
import time
import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Avg, Q
from django.http import JsonResponse, Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_GET
from core.models import (DemoExperience, DemoRevision, DemoSession, DemoEvent, DemoFeedback,
                         DemoRepAccess, DemoShareLink, DemoConversion, DemoCRMLead, DemoCRMActivity)
from core.rate_limits import consume_budget, request_identity
from core.demo_profiles import resolve_profile
from .access import manager, salesperson, browser_key, share_token, resolve_share, assessment_token
from . import tools, engine
from .financing import DemoFinanceForm, FINANCING_CHOICES, SAMPLE_PROFILES, open_application, submit_application

logger = logging.getLogger(__name__)


def payload(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, UnicodeDecodeError):
        return {}


def experience(request):
    obj = get_object_or_404(DemoExperience.objects.select_related("current_revision"), slug="automotive", current_revision__isnull=False)
    if (not obj.published or not obj.public_access) and not salesperson(request.user):
        raise Http404()
    return obj


def owned_session(request, pk):
    try:
        session = DemoSession.objects.select_related("revision__experience", "rep").get(pk=pk, browser_key=browser_key(request))
    except (DemoSession.DoesNotExist, ValueError, TypeError, ValidationError):
        raise Http404()
    exp = session.revision.experience
    if session.ended_at or session.expires_at <= timezone.now() or ((not exp.published or not exp.public_access) and not salesperson(request.user)):
        raise Http404()
    return session


def public_state(session):
    return {"id": str(session.pk), "scenario": session.scenario, "state": {k: v for k, v in session.state.items() if k not in ("offered_slots", "last_request", "crm_actions")},
            "transcript": session.transcript, "turns": session.turns, "revision": session.revision.version,
            "finance_options": [{"stock": v["stock"], "label": f"{v['year']} {v['make']} {v['model']} · {v['stock']}"} for v in session.revision.content["inventory"] if v["status"] == "available"] if session.state.get("financing_application", {}).get("status") == "draft" else [],
            "assessment_url": reverse("growth_assessment") + "?demo_ref=" + assessment_token(session) + "#assessment-request"}


def error(message, code="unavailable", status=400):
    return JsonResponse({"error": message, "code": code}, status=status)


@never_cache
@ensure_csrf_cookie
def automotive(request):
    exp = experience(request)
    browser_key(request)
    scenarios = [s for s in exp.current_revision.content["scenarios"] if s.get("enabled", True)]
    link = resolve_share(request.GET.get("ref", ""), exp)
    initial = link.scenario if link else "vehicle-shopping"
    if initial not in {s["slug"] for s in scenarios}:
        initial = scenarios[0]["slug"] if scenarios else ""
    config = {"base": reverse("experience_home"), "sessionUrl": reverse("experience_session"), "turnUrl": reverse("experience_turn"),
              "voiceUrl": reverse("experience_transcribe"), "speechUrl": reverse("experience_speech"), "actionUrl": reverse("experience_action"),
              "crmUrl": reverse("experience_crm"), "financeUrl": reverse("experience_finance"), "sampleProfiles": SAMPLE_PROFILES,
              "ready": bool(settings.PLATFORM_OPENAI_API_KEY), "salesperson": salesperson(request.user),
              "scenario": initial, "scenarios": [{k: s[k] for k in ("slug", "title", "label", "pain", "starter")} for s in scenarios],
              "ref": request.GET.get("ref", "") if link else ""}
    return render(request, "core/experience/automotive.html", {"experience": exp, "demo_config": config,
        "portrait": resolve_profile("automotive")["portrait"], "is_rep": salesperson(request.user), "is_manager": manager(request.user), "scenarios": scenarios,
        "finance_form": DemoFinanceForm(content=exp.current_revision.content, prefix="finance")})


@never_cache
@require_POST
def session_start(request):
    exp = experience(request)
    data = payload(request)
    if data.get("resume"):
        session = owned_session(request, data["resume"])
        return JsonResponse(public_state(session))
    if not consume_budget("experience-start", request_identity(request), limit=40 if salesperson(request.user) else 12, window=3600):
        return error("Too many new demos. Please wait before starting another.", "rate_limit", 429)
    link = resolve_share(data.get("ref", ""), exp)
    default_scenario = link.scenario if link else "vehicle-shopping"
    scenario = data.get("scenario", default_scenario) if salesperson(request.user) else default_scenario
    enabled = [s["slug"] for s in exp.current_revision.content["scenarios"] if s.get("enabled", True)]
    if scenario not in enabled:
        if not enabled:
            return error("This demo is temporarily unavailable.", status=503)
        scenario = enabled[0]
    rep = request.user if salesperson(request.user) else link.rep if link else None
    session = DemoSession.objects.create(revision=exp.current_revision, browser_key=browser_key(request), rep=rep,
        source="field" if salesperson(request.user) else "share" if link else "public", scenario=scenario,
        state=tools.initial_state(scenario), expires_at=timezone.now() + timedelta(hours=8 if salesperson(request.user) else 2))
    DemoEvent.objects.create(session=session, kind="started")
    return JsonResponse(public_state(session), status=201)


@never_cache
@require_POST
def turn(request):
    data = payload(request)
    session = owned_session(request, data.get("session"))
    message = data.get("message", "")
    if not isinstance(message, str) or not message.strip() or len(message) > 1600:
        return error("Enter a message of up to 1,600 characters.")
    mode = data.get("mode", "text")
    if mode not in ("text", "voice"):
        return error("Choose Speak or Type.")
    try:
        request_id = str(uuid.UUID(data.get("request_id", "")))
    except (ValueError, TypeError, AttributeError):
        return error("Please retry this message.")
    if session.state.get("last_request") == request_id:
        return JsonResponse(public_state(session))
    if not settings.PLATFORM_OPENAI_API_KEY:
        return error("Live conversation isn't connected in this preview. You can still explore the demo inventory.", "not_configured", 503)
    if session.turns >= (100 if salesperson(request.user) else 30):
        return error("This conversation has reached its demo limit. Your dealership view is still available.", "session_limit", 429)
    if not consume_budget("experience-turn", request_identity(request), limit=180 if salesperson(request.user) else 60, window=3600):
        return error("Please give the demo a little time before sending more messages.", "rate_limit", 429)
    lease = uuid.uuid4()
    now = timezone.now()
    acquired = DemoSession.objects.filter(pk=session.pk, ended_at__isnull=True).filter(Q(busy_until__isnull=True) | Q(busy_until__lt=now)).update(lease=lease, busy_until=now + timedelta(seconds=75))
    if not acquired:
        return error("Axel is finishing your last request. Please wait a moment.", "busy", 409)
    session.refresh_from_db()
    if session.state.get("last_request") == request_id:
        DemoSession.objects.filter(pk=session.pk, lease=lease).update(lease=None, busy_until=None)
        return JsonResponse(public_state(session))
    started = time.monotonic()
    try:
        session.state["comparison"] = False
        answer, events, latency = engine.converse(session, message.strip(), request.user, mode)
        session.transcript += [{"role": "user", "content": message.strip(), "mode": mode}, {"role": "assistant", "content": answer}]
        session.transcript = session.transcript[-200:]
        session.state["last_request"] = request_id
        with transaction.atomic():
            locked = DemoSession.objects.select_for_update().get(pk=session.pk)
            if locked.lease != lease or locked.ended_at:
                return error("This demo was reset. Start a new conversation.", "reset", 409)
            tools.sync_crm(session)
            session.turns += 1
            session.lease = None
            session.busy_until = None
            session.save(update_fields=["state", "transcript", "protocol", "turns", "lease", "busy_until", "updated_at"])
            DemoEvent.objects.bulk_create([DemoEvent(session=session, **e) for e in events] + [DemoEvent(session=session, kind="turn", metadata={"mode": mode, "behavior": engine.BEHAVIOR_VERSION}, latency_ms=latency)])
        return JsonResponse(public_state(session))
    except Exception as exc:
        # Never log the prompt, transcript, provider response body or credentials.
        logger.warning("Experience turn failed session=%s error=%s", session.pk, type(exc).__name__)
        DemoEvent.objects.create(session=session, kind="llm_error", metadata={"error": type(exc).__name__}, latency_ms=round((time.monotonic() - started) * 1000))
        return error("The connection to Axel was interrupted. Your conversation is saved; try that message again.", "ai_unavailable", 503)
    finally:
        DemoSession.objects.filter(pk=session.pk, lease=lease).update(lease=None, busy_until=None)


@never_cache
@require_POST
def action(request):
    data = payload(request)
    session = owned_session(request, data.get("session"))
    kind = data.get("action")
    if not consume_budget("experience-actions", request_identity(request), limit=120, window=60):
        return error("Please wait a moment.", "rate_limit", 429)
    if kind == "reset":
        with transaction.atomic():
            locked = DemoSession.objects.select_for_update().get(pk=session.pk)
            locked.state, locked.transcript, locked.protocol = {}, [], []
            locked.ended_at, locked.lease, locked.busy_until = timezone.now(), None, None
            locked.save()
            DemoCRMLead.objects.filter(session=locked).delete()
            DemoEvent.objects.create(session=locked, kind="reset")
        request.session.pop("experience_crm:" + str(session.pk), None)
        return JsonResponse({"reset": True})
    if kind == "handoff":
        DemoEvent.objects.create(session=session, kind="handoff_viewed")
        return JsonResponse(tools.handoff(session))
    if kind == "inventory":
        try:
            args = tools.Search.model_validate(data.get("filters", {})).model_dump()
        except Exception:
            return error("Please check the inventory filters.")
        DemoEvent.objects.create(session=session, kind="inventory_browsed")
        return JsonResponse(tools.search_inventory(session.revision.content, args))
    if kind in ("assessment_clicked", "voice_error", "presentation", "audio_started"):
        DemoEvent.objects.create(session=session, kind=kind)
        return JsonResponse({"ok": True})
    if kind == "share":
        link = DemoShareLink.objects.create(experience=session.revision.experience, rep=session.rep, scenario=session.scenario)
        return JsonResponse({"url": request.build_absolute_uri(reverse("experience_home")) + "?ref=" + share_token(link)})
    if kind == "feedback" and salesperson(request.user):
        if data.get("category") not in dict(DemoFeedback.CATEGORIES) or not isinstance(data.get("notes"), str) or not 1 <= len(data["notes"].strip()) <= 2000:
            return error("Choose an issue and enter a short description.")
        DemoFeedback.objects.create(session=session, rep=request.user, category=data["category"], notes=data["notes"].strip())
        return JsonResponse({"ok": True})
    return error("That action is not available.", status=403)


def voice_budget(request, session):
    return (settings.PLATFORM_OPENAI_API_KEY and
        consume_budget("experience-voice-session", str(session.pk), limit=160 if salesperson(request.user) else 60, window=3600) and
        consume_budget("experience-voice-ip", request_identity(request), limit=240 if salesperson(request.user) else 90, window=3600) and
        consume_budget("experience-voice-global", "platform", limit=getattr(settings, "DEMO_VOICE_DAILY_LIMIT", 600), window=86400))


@never_cache
@require_POST
def finance(request):
    data = payload(request)
    original = owned_session(request, data.get("session"))
    if not consume_budget("experience-finance", request_identity(request), limit=30, window=60):
        return error("Please wait a moment before trying the application again.", "rate_limit", 429)
    with transaction.atomic():
        session = DemoSession.objects.select_for_update().select_related("revision__experience").get(pk=original.pk)
        if session.ended_at or session.expires_at <= timezone.now():
            raise Http404()
        if session.busy_until and session.busy_until > timezone.now():
            return error("Axel is finishing your last message. Please try again in a moment.", "busy", 409)
        if data.get("action") == "open":
            stock = data.get("stock")
            if stock is not None and (not isinstance(stock, str) or len(stock) > 30):
                return error("Choose an available demo vehicle.")
            try:
                open_application(session, stock)
            except ValueError as exc:
                return error(str(exc))
        elif data.get("action") == "submit":
            application = session.state.get("financing_application")
            if not application or data.get("application_id") != application["id"]:
                return error("Open this demo's application before submitting it.", "application_missing", 409)
            # A retry must not create a second submission or a second activity entry.
            if application["status"] == "submitted":
                return JsonResponse(public_state(session))
            fields = data.get("fields")
            if not isinstance(fields, dict) or set(fields) - set(DemoFinanceForm.base_fields):
                return error("Use only the displayed demo fields. Sensitive financial identifiers are not accepted.")
            form = DemoFinanceForm(fields, content=session.revision.content)
            if not form.is_valid():
                return JsonResponse({"error": "Please check the highlighted application fields.", "errors": form.errors.get_json_data()}, status=400)
            submit_application(session, form.cleaned_data)
            DemoEvent.objects.create(session=session, kind="finance_submitted")
        else:
            return error("Choose an available application action.")
        tools.sync_crm(session)
        session.save(update_fields=["state", "updated_at"])
    return JsonResponse(public_state(session))


@never_cache
@require_POST
def transcribe(request):
    """Raw bounded audio stays in memory; no Django file upload or media storage."""
    session = owned_session(request, request.GET.get("session"))
    mime = request.content_type
    if mime not in ("audio/webm", "audio/mp4", "audio/ogg", "audio/wav"):
        return error("This browser's microphone format is unsupported. Please type instead.")
    if int(request.META.get("CONTENT_LENGTH") or 0) > 2_000_000:
        return error("Please use a shorter voice message.", status=413)
    if not voice_budget(request, session):
        return error("Voice is unavailable right now. Please type instead.", "voice_limit", 429)
    raw = request.body
    if not 200 < len(raw) <= 2_000_000:
        return error("We didn't catch that. Try a short voice message, or type instead.")
    from openai import OpenAI
    from assistant_ai.services import PlatformAIService
    started = time.monotonic()
    try:
        response = OpenAI(api_key=settings.PLATFORM_OPENAI_API_KEY, max_retries=0).audio.transcriptions.create(
            model="gpt-4o-mini-transcribe", file=("speech." + {"audio/webm": "webm", "audio/mp4": "mp4", "audio/ogg": "ogg", "audio/wav": "wav"}[mime], raw, mime), timeout=18)
        text = response.text.strip()[:1600]
        PlatformAIService(user=request.user, assistant_role="experience_voice")._record_usage(model="gpt-4o-mini-transcribe", metadata={"bytes": len(raw)})
        DemoEvent.objects.create(session=session, kind="transcribed", latency_ms=round((time.monotonic() - started) * 1000))
        return JsonResponse({"text": text})
    except Exception as exc:
        logger.warning("Experience transcription failed error=%s", type(exc).__name__)
        DemoEvent.objects.create(session=session, kind="voice_error", metadata={"stage": "transcription", "error": type(exc).__name__})
        return error("We couldn't hear that clearly. Try again or type your message.", "voice_error", 503)


@never_cache
@require_POST
def speech(request):
    data = payload(request)
    session = owned_session(request, data.get("session"))
    last = session.transcript[-1] if session.transcript else {}
    if last.get("role") != "assistant" or data.get("turn") != session.turns:
        return error("That spoken reply is no longer available.")
    if not voice_budget(request, session):
        return error("Spoken replies are unavailable. The reply is still in your conversation.", "voice_limit", 429)
    from openai import OpenAI
    from assistant_ai.services import PlatformAIService
    started = time.monotonic()
    try:
        stream = OpenAI(api_key=settings.PLATFORM_OPENAI_API_KEY, max_retries=0).audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts", voice="cedar", input=last["content"][:4000], response_format="mp3",
            instructions="A warm, confident dealership concierge. Natural conversational pacing; friendly, concise, not a radio announcer.", timeout=18)
        response = stream.__enter__()
    except Exception as exc:
        DemoEvent.objects.create(session=session, kind="voice_error", metadata={"stage": "speech", "error": type(exc).__name__})
        return error("Audio isn't available. You can read Axel's reply below.", "voice_error", 503)

    def audio_chunks():
        try:
            yield from response.iter_bytes(chunk_size=4096)
            PlatformAIService(user=request.user, assistant_role="experience_voice")._record_usage(model="gpt-4o-mini-tts", metadata={"characters": len(last["content"])})
            DemoEvent.objects.create(session=session, kind="speech_delivered", latency_ms=round((time.monotonic() - started) * 1000))
        except Exception as exc:
            logger.warning("Experience audio stream failed error=%s", type(exc).__name__)
            DemoEvent.objects.create(session=session, kind="voice_error", metadata={"stage": "stream", "error": type(exc).__name__})
        finally:
            stream.__exit__(None, None, None)
    result = StreamingHttpResponse(audio_chunks(), content_type="audio/mpeg")
    result["X-Accel-Buffering"] = "no"
    return result


@never_cache
@ensure_csrf_cookie
def dealership_crm(request):
    session = owned_session(request, request.GET.get("session"))
    auth_key = "experience_crm:" + str(session.pk)
    if request.method == "POST":
        if request.POST.get("action") == "signin":
            # This is explicitly a simulated staff identity, never real authentication.
            request.session[auth_key] = True
            DemoEvent.objects.create(session=session, kind="crm_signed_in")
        elif request.POST.get("action") == "signout":
            request.session.pop(auth_key, None)
        elif request.session.get(auth_key) and request.POST.get("action") == "update":
            lead = get_object_or_404(DemoCRMLead, session=session)
            stage = request.POST.get("stage")
            notes = request.POST.get("notes", "").strip()
            assigned = request.POST.get("assigned_to")
            if stage in ("new", "discovery", "qualified", "appointment", "follow_up", "closed") and len(notes) <= 3000 and assigned in ("Elena Rivera · BDC", "Marcus Reed · Sales", "Jordan Ellis · Service", "Alex Morgan · Finance"):
                with transaction.atomic():
                    lead = DemoCRMLead.objects.select_for_update().get(pk=lead.pk)
                    lead.stage, lead.staff_notes, lead.assigned_to = stage, notes, assigned
                    lead.save(update_fields=["stage", "staff_notes", "assigned_to", "updated_at"])
                    DemoCRMActivity.objects.create(lead=lead, action="Demo staff updated customer", description=f"Stage: {stage.replace('_', ' ')} · Assigned to {assigned}")
                messages.success(request, "Fictional customer record updated. No real CRM was changed.")
        return redirect(reverse("experience_crm") + "?session=" + str(session.pk))
    logged_in = bool(request.session.get(auth_key))
    lead = DemoCRMLead.objects.filter(session=session).first() if logged_in else None
    if logged_in:
        DemoEvent.objects.create(session=session, kind="crm_viewed")
    return render(request, "core/experience/crm.html", {"session": session, "demo_login": logged_in, "lead": lead,
        "handoff": tools.handoff(session) if logged_in else None,
        "purchase_plan": dict(FINANCING_CHOICES).get(session.state.get("customer", {}).get("financing_preference", ""), ""),
        "activity": lead.activity.order_by("-created_at")[:50] if lead else [],
        "state_url": reverse("experience_crm_state") + "?session=" + str(session.pk)})


@never_cache
@require_GET
def crm_state(request):
    session = owned_session(request, request.GET.get("session"))
    if not request.session.get("experience_crm:" + str(session.pk)):
        return error("Enter the fictional dealership workspace first.", status=403)
    lead = DemoCRMLead.objects.filter(session=session).first()
    return JsonResponse({"has_customer": bool(lead), "updated": lead.updated_at.isoformat() if lead else "", "turns": session.turns})


@never_cache
@login_required
def rep_guide(request):
    if not salesperson(request.user):
        raise Http404()
    return render(request, "core/experience/guide.html")


def validate_content(content):
    """Managers edit data, not executable tools or system instructions."""
    if not isinstance(content, dict) or len(json.dumps(content)) > 300000:
        raise ValueError("Content must be a JSON object under 300 KB.")
    business = content.get("business", {})
    if not isinstance(business, dict):
        raise ValueError("Business must be an object.")
    for key in ("name", "employee", "address", "phone", "timezone", "hours", "team", "departments", "policies", "faqs", "promotions"):
        if key not in business:
            raise ValueError(f"Business is missing {key}.")
    from zoneinfo import ZoneInfo
    if not isinstance(business["timezone"], str):
        raise ValueError("Choose a valid timezone name.")
    ZoneInfo(business["timezone"])
    if not isinstance(business["hours"], dict) or not isinstance(business["policies"], dict):
        raise ValueError("Hours and policies must be objects.")
    for key in ("name", "employee", "address", "phone"):
        if not isinstance(business[key], str) or not 1 <= len(business[key]) <= 300:
            raise ValueError(f"Business {key} needs 1–300 characters.")
    from .data import BUSINESS
    if not set(BUSINESS["policies"]).issubset(business["policies"]) or any(not isinstance(v, str) or len(v) > 4000 for v in business["policies"].values()):
        raise ValueError("Retain the approved policy topics as text of at most 4,000 characters each.")
    if not isinstance(business["faqs"], list) or not 1 <= len(business["faqs"]) <= 100 or any(not isinstance(f, dict) or any(not isinstance(f.get(k), str) or len(f[k]) > 2000 for k in ("question", "answer")) for f in business["faqs"]):
        raise ValueError("Supply 1–100 FAQ question/answer pairs.")
    for department in ("sales", "service", "finance", "bdc"):
        if not isinstance(business["hours"].get(department), dict):
            raise ValueError("Each department needs hours.")
    vehicles = content.get("inventory")
    if not isinstance(vehicles, list) or not 1 <= len(vehicles) <= 150:
        raise ValueError("Supply 1–150 synthetic vehicles.")
    from .data import inventory
    required = set(inventory()[0])
    stocks = set()
    for v in vehicles:
        if not isinstance(v, dict) or not required.issubset(v) or not v.get("synthetic"):
            raise ValueError("Each vehicle must retain the full seeded field set and synthetic=true.")
        if v["stock"] in stocks or not isinstance(v["stock"], str) or not v["stock"].startswith("VM-"):
            raise ValueError("Use unique VM- stock numbers.")
        stocks.add(v["stock"])
        if v["status"] not in ("available", "pending", "sold") or v["condition"] not in ("new", "used", "certified"):
            raise ValueError("Vehicle status/condition is invalid.")
        if any(type(v[k]) is not int or v[k] < 0 for k in ("price", "mileage", "year", "seating", "rows")):
            raise ValueError("Vehicle prices, year, mileage, seats and rows must be non-negative integers.")
        if not isinstance(v["features"], list) or len(v["features"]) > 30 or any(not isinstance(f, str) or len(f) > 150 for f in v["features"]):
            raise ValueError("Features must be a list of up to 30 short descriptions.")
        if any(not isinstance(v[k], str) or len(v[k]) > 150 for k in ("make", "model", "trim", "engine", "fuel_type", "drivetrain", "efficiency", "exterior_color", "interior_color", "body_style")):
            raise ValueError("Vehicle descriptions must be short text fields.")
        if v["special_price"] is not None and (type(v["special_price"]) is not int or not 0 <= v["special_price"] <= v["price"]):
            raise ValueError("Special prices must be between zero and the regular demo price.")
        if not isinstance(v["image"], str) or not v["image"].startswith("img/experience/") or ".." in v["image"] or ":" in v["image"]:
            raise ValueError("Images must use local experience assets.")
    from .data import SCENARIOS
    allowed = {s[0] for s in SCENARIOS}
    scenarios = content.get("scenarios", [])
    if not isinstance(scenarios, list) or any(not isinstance(s, dict) for s in scenarios):
        raise ValueError("Scenarios must be a list of objects.")
    if len(scenarios) != len(allowed) or {s.get("slug") for s in scenarios} != allowed:
        raise ValueError("Retain the ten scenario IDs; use enabled=false to disable a scenario.")
    for scenario in scenarios:
        if any(not isinstance(scenario.get(k), str) or len(scenario[k]) > 2000 for k in ("title", "label", "pain", "context", "starter")) or type(scenario.get("enabled")) is not bool:
            raise ValueError("Each scenario needs text fields and an enabled boolean.")
    if not any(s["enabled"] for s in scenarios):
        raise ValueError("Keep at least one scenario enabled or unpublish the entire demo.")
    return content


@never_cache
@login_required
def manage(request):
    if not manager(request.user):
        raise Http404()
    exp = DemoExperience.objects.select_related("current_revision").filter(slug="automotive").first()
    problem = ""
    if request.method == "POST":
        try:
            kind = request.POST.get("action")
            if kind == "publish" and exp:
                exp.published = request.POST.get("published") == "on"
                exp.public_access = request.POST.get("public_access") == "on"
                exp.save(update_fields=["published", "public_access"])
            elif kind == "content" and exp:
                content = validate_content(json.loads(request.POST.get("content", "")))
                with transaction.atomic():
                    revision = DemoRevision.objects.create(experience=exp, version="velocity-" + timezone.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8], content=content, created_by=request.user)
                    exp.current_revision = revision
                    exp.save(update_fields=["current_revision"])
            elif kind == "access":
                from accounts.models import User
                employee = get_object_or_404(User, pk=request.POST.get("user"), role__in=["employee", "admin", "owner"])
                if employee.pk == request.user.pk:
                    raise ValueError("You cannot revoke your own demo access here.")
                DemoRepAccess.objects.update_or_create(user=employee, defaults={"enabled": request.POST.get("enabled") == "on"})
            elif kind == "feedback":
                DemoFeedback.objects.filter(pk=request.POST.get("feedback")).update(resolved=True)
            elif kind == "seed":
                from django.core.management import call_command
                call_command("seed_demo_center", restore_seed=True)
            else:
                raise ValueError("Choose an available management action.")
            messages.success(request, "Demo Center updated. Existing conversations retain their content version.")
            return redirect("experience_manage")
        except (ValueError, TypeError, KeyError) as exc:
            problem = str(exc)[:200]
    days = int(request.GET.get("days", 30)) if request.GET.get("days", "30") in ("7", "30", "90") else 30
    start = timezone.now() - timedelta(days=days)
    sessions = DemoSession.objects.filter(created_at__gte=start)
    rep_id = request.GET.get("rep", "")
    if rep_id.isdigit():
        sessions = sessions.filter(rep_id=rep_id)
    events = DemoEvent.objects.filter(session__in=sessions)
    counts = {r["kind"]: r["n"] for r in events.values("kind").annotate(n=Count("pk"))}
    modes = {r["metadata__mode"]: r["n"] for r in events.filter(kind="turn").values("metadata__mode").annotate(n=Count("pk"))}
    workflow = list(events.filter(kind="tool").values("metadata__name").annotate(n=Count("pk")).order_by("-n"))
    from accounts.models import User
    reps = list(User.objects.filter(role__in=["employee", "owner", "admin"]).order_by("first_name", "username"))
    disabled = set(DemoRepAccess.objects.filter(enabled=False).values_list("user_id", flat=True))
    for rep in reps:
        rep.demo_enabled = rep.pk not in disabled
    return render(request, "core/experience/manage.html", {"experience": exp, "problem": problem,
        "content_json": json.dumps(exp.current_revision.content, indent=2) if exp and exp.current_revision else "",
        "days": days, "rep_filter": rep_id, "reps": reps, "session_count": sessions.count(), "counts": counts, "modes": modes,
        "latency": round((events.filter(kind="turn").aggregate(ms=Avg("latency_ms"))["ms"] or 0) / 1000, 1),
        "conversions": DemoConversion.objects.filter(session__in=sessions).count(), "workflow": workflow,
        "scenarios": sessions.values("scenario").annotate(n=Count("pk")).order_by("-n"),
        "recent": sessions.select_related("rep", "revision").order_by("-created_at")[:50],
        "feedback": DemoFeedback.objects.filter(session__in=sessions).select_related("rep", "session").order_by("resolved", "-created_at")[:50]})


@never_cache
@require_GET
def qr(request):
    session = owned_session(request, request.GET.get("session"))
    if not consume_budget("experience-qr", request_identity(request), limit=30, window=3600):
        return error("Please reuse the share link already generated.", "rate_limit", 429)
    from io import BytesIO
    import qrcode
    import qrcode.image.svg
    link = DemoShareLink.objects.create(experience=session.revision.experience, rep=session.rep, scenario=session.scenario)
    url = request.build_absolute_uri(reverse("experience_home")) + "?ref=" + share_token(link)
    output = BytesIO()
    qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, border=4).save(output)
    return HttpResponse(output.getvalue(), content_type="image/svg+xml")


@require_GET
def manifest(request):
    from django.templatetags.static import static
    return JsonResponse({"name": "AIBG Experience Center", "short_name": "AIBG Demo", "id": "/demo/automotive/", "start_url": "/demo/automotive/?presentation=1",
        "scope": "/demo/automotive/", "display": "standalone", "background_color": "#0c0c12", "theme_color": "#0c0c12",
        "icons": [{"src": static("img/ai-business-gurus-logo.png"), "sizes": "any", "type": "image/png"}]}, content_type="application/manifest+json")
