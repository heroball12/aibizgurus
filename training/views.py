import json
import math
import uuid
from datetime import timedelta
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
    ImproperlyConfigured,
)
from django.db import transaction
from django.http import JsonResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_safe
from django.conf import settings
from core.permissions import employee_required
from core.rate_limits import consume_budget
from .models import (
    Track,
    ModuleVersion,
    EmployeeProgress,
    QuizAttempt,
    RolePlayScenario,
    RolePlayAttempt,
    EmployeeSkill,
    Skill,
    CertificationAttempt,
    TrainingAssignment,
    ManagerReview,
    ProctorSession,
    ProgressTransfer,
)
from . import services, proctor


def payload(request):
    if len(request.body) > 30000:
        raise ValidationError("Keep the submission under 30 KB.")
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise ValidationError("Invalid submission.")
    if not isinstance(data, dict):
        raise ValidationError("Invalid submission.")
    return data


def failure(exc):
    return JsonResponse(
        {
            "error": (
                " ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            )
        },
        status=400,
    )


def lesson_for(request, pk):
    version = get_object_or_404(
        ModuleVersion.objects.select_related("module__track").prefetch_related(
            "assets"
        ),
        pk=pk,
    )
    if not services.is_manager(request.user) and not services.can_preview_locally(
        request.user, version
    ):
        services.require_learning(request.user, version)
    return version


@employee_required
@never_cache
def home(request):
    enrollments = list(
        CertificationAttempt.objects.filter(employee=request.user).select_related(
            "track"
        )
    )
    panels = []
    continuation = None
    assessment_continuation = None
    for enrollment in enrollments:
        cards = []
        for module in enrollment.track.modules.all():
            version = (
                module.versions.filter(status="published").order_by("-number").first()
            )
            local_preview = False
            if not version:
                candidate = (
                    module.versions.filter(status="owner_review")
                    .order_by("-number")
                    .first()
                )
                if candidate and services.can_preview_locally(request.user, candidate):
                    version = candidate
                    local_preview = True
            assignment = (
                enrollment.assignments.filter(version__module=module, active=True)
                .order_by("-created_at")
                .first()
            )
            state = (
                services.module_state(
                    request.user,
                    version,
                    (
                        assignment.created_at
                        if assignment and assignment.retraining
                        else None
                    ),
                )
                if version and not local_preview
                else None
            )
            cards.append(
                {
                    "module": module,
                    "version": version,
                    "state": state,
                    "local_preview": local_preview,
                }
            )
            if state and not state["complete"]:
                if state["credited_video"]:
                    assessment_continuation = assessment_continuation or version
                else:
                    continuation = continuation or version
        panels.append(
            {
                "enrollment": enrollment,
                "cards": cards,
                "certified": enrollment.certifications.filter(
                    revoked_at__isnull=True
                ).exists(),
                "complete": sum(
                    bool(c["state"] and c["state"]["complete"]) for c in cards
                ),
                "total": len(cards),
            }
        )
    return render(
        request,
        "training/home.html",
        {
            "panels": panels,
            "continue_version": continuation or assessment_continuation,
            "tracks": Track.objects.filter(is_active=True),
            "is_training_manager": services.is_manager(request.user),
        },
    )


@employee_required
@never_cache
def lesson(request, pk):
    version = lesson_for(request, pk)
    official = services.can_learn(request.user, version)
    state = services.module_state(request.user, version) if official else None
    quiz = getattr(version, "quiz", None)
    return render(
        request,
        "training/lesson.html",
        {
            "version": version,
            "official": official,
            "local_preview": not official
            and services.can_preview_locally(request.user, version),
            "state": state,
            "quiz": quiz,
            "questions": quiz.questions.all() if quiz else [],
            "quiz_nonce": uuid.uuid4(),
            "attempts": (
                QuizAttempt.objects.filter(employee=request.user, quiz=quiz).order_by(
                    "-created_at"
                )[:12]
                if quiz
                else []
            ),
            "scenarios": version.scenarios.all(),
            "watch_session": uuid.uuid4(),
            "assets": {a.kind: a for a in version.assets.all()},
            "is_training_manager": services.is_manager(request.user),
            "owner": request.user.is_owner(),
        },
    )


@employee_required
@never_cache
@require_safe
def asset(request, pk, kind):
    version = lesson_for(request, pk)
    obj = get_object_or_404(version.assets, kind=kind)
    from .media import media_url, local_response

    try:
        if not settings.TRAINING_S3_BUCKET and settings.TRAINING_MEDIA_ROOT:
            return local_response(request, obj)
        url = media_url(obj)
    except (ImproperlyConfigured, ValidationError):
        return JsonResponse({"error": "Training media is being prepared."}, status=503)
    except Exception:
        return JsonResponse(
            {
                "error": "Media access is temporarily unavailable. Reload the player to retry."
            },
            status=503,
        )
    response = redirect(url)
    response["Cache-Control"] = "private, no-store"
    return response


@employee_required
@never_cache
@require_POST
def progress(request, pk):
    version = lesson_for(request, pk)
    try:
        services.heartbeat(request.user, version, payload(request))
        return JsonResponse(services.module_state(request.user, version))
    except ValidationError as exc:
        return failure(exc)


@employee_required
@never_cache
@require_POST
def quiz_submit(request, pk):
    version = lesson_for(request, pk)
    quiz = getattr(version, "quiz", None)
    if not quiz:
        raise Http404()
    if not consume_budget("training-quiz", str(request.user.pk), limit=20, window=3600):
        return JsonResponse(
            {"error": "Take time to review the explanations before another attempt."},
            status=429,
        )
    try:
        data = payload(request)
        attempt = services.submit_quiz(
            request.user, quiz, data.get("answers"), data.get("nonce")
        )
        return JsonResponse(
            {
                "id": str(attempt.pk),
                "score": attempt.score,
                "passed": attempt.passed,
                "threshold": attempt.pass_percent,
                "feedback": attempt.feedback,
            }
        )
    except ValidationError as exc:
        return failure(exc)


@employee_required
@never_cache
@require_POST
def practice_start(request, pk):
    scenario = get_object_or_404(
        RolePlayScenario.objects.select_related("version__module__track"), pk=pk
    )
    services.require_learning(request.user, scenario.version)
    if not consume_budget(
        "training-practice-start", str(request.user.pk), limit=30, window=3600
    ):
        return HttpResponse("Practice limit reached. Please return later.", status=429)
    previous = (
        RolePlayAttempt.objects.filter(employee=request.user, scenario=scenario)
        .exclude(state="active")
        .order_by("-created_at")
        .first()
    )
    attempt = RolePlayAttempt.objects.create(
        employee=request.user,
        scenario=scenario,
        previous=previous,
        transcript=[{"role": "assistant", "content": scenario.opening}],
    )
    return redirect("training_practice", pk=attempt.pk)


@employee_required
@never_cache
def practice(request, pk):
    attempt = get_object_or_404(
        RolePlayAttempt.objects.select_related("scenario__version__module__track"),
        pk=pk,
        employee=request.user,
    )
    return render(
        request,
        "training/practice.html",
        {
            "attempt": attempt,
            "version": attempt.scenario.version,
            "text_ai": bool(proctor.settings.PLATFORM_OPENAI_API_KEY),
            "skills": Skill.objects.filter(slug__in=attempt.scenario.rubric.keys()),
            "evidence": EmployeeSkill.objects.filter(attempt=attempt),
            "previous": attempt.previous,
        },
    )


@employee_required
@never_cache
@require_POST
def practice_turn(request, pk):
    try:
        data = payload(request)
        text = data.get("message", "")
        nonce = str(uuid.UUID(str(data.get("nonce", ""))))
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
            raise ValidationError("Use 1–2,000 characters.")
    except (ValueError, TypeError):
        return JsonResponse(
            {"error": "Reload the practice before sending."}, status=400
        )
    except ValidationError as exc:
        return failure(exc)
    with transaction.atomic():
        attempt = get_object_or_404(
            RolePlayAttempt.objects.select_for_update().select_related(
                "scenario__version__module__track"
            ),
            pk=pk,
            employee=request.user,
        )
        services.require_learning(request.user, attempt.scenario.version)
        if attempt.state != "active":
            return JsonResponse(
                {"error": "This attempt is closed. Start a retry."}, status=409
            )
        if any(m.get("nonce") == nonce for m in attempt.transcript):
            return JsonResponse({"transcript": attempt.transcript})
        if (
            attempt.busy
            and attempt.processing_at
            and attempt.processing_at > timezone.now() - timedelta(seconds=90)
        ):
            return JsonResponse(
                {"error": "Guru is responding. Please wait."}, status=409
            )
        if len(attempt.transcript) >= 42:
            return JsonResponse(
                {"error": "Finish this attempt and prepare your CRM handoff."},
                status=400,
            )
        if not consume_budget(
            "training-practice", str(request.user.pk), limit=60, window=3600
        ):
            return JsonResponse(
                {"error": "Practice limit reached. Please return later."}, status=429
            )
        attempt.busy = True
        attempt.processing_at = timezone.now()
        attempt.save(update_fields=["busy", "processing_at"])
    history = [{k: m[k] for k in ["role", "content"]} for m in attempt.transcript] + [
        {"role": "user", "content": text.strip()}
    ]
    try:
        response = proctor.reply(
            request.user,
            attempt.scenario.version,
            history,
            "roleplay",
            attempt.scenario,
        )
    except Exception:
        response = None
    guided = not bool(response)
    if guided:
        response = proctor.guided_reply(history)
    with transaction.atomic():
        current = RolePlayAttempt.objects.select_for_update().get(pk=attempt.pk)
        if current.state != "active" or current.processing_at != attempt.processing_at:
            return JsonResponse(
                {"error": "This response was superseded. Reload the practice."},
                status=409,
            )
        current.transcript += [
            {"role": "user", "content": text.strip(), "nonce": nonce},
            {"role": "assistant", "content": response},
        ]
        current.busy = False
        current.processing_at = None
        current.save()
    return JsonResponse({"transcript": current.transcript, "guided": guided})


@employee_required
@never_cache
@require_POST
def practice_finish(request, pk):
    submitted = False
    with transaction.atomic():
        attempt = get_object_or_404(
            RolePlayAttempt.objects.select_for_update(), pk=pk, employee=request.user
        )
        if attempt.state != "active":
            return redirect("training_practice", pk=attempt.pk)
        handoff = request.POST.get("handoff", "").strip()
        if (
            not handoff
            or len(handoff) > 5000
            or not any(m["role"] == "user" for m in attempt.transcript)
        ):
            messages.error(
                request,
                "Practice the conversation and add a factual handoff (up to 5,000 characters) first.",
            )
        elif attempt.busy:
            messages.error(request, "Wait for Guru’s reply before submitting.")
        else:
            attempt.handoff = handoff
            attempt.state = "review"
            attempt.save()
            submitted = True
            messages.success(
                request, "Practice saved for manager review. This does not certify you."
            )
    if submitted:
        proctor.assess(attempt)
    return redirect("training_practice", pk=attempt.pk)


@employee_required
@never_cache
@require_POST
def proctor_start(request):
    mode = request.POST.get("mode", "coach")
    if mode not in proctor.MODES:
        raise Http404()
    version = (
        lesson_for(request, request.POST["version"])
        if request.POST.get("version", "").isdigit()
        else None
    )
    session = ProctorSession.objects.create(
        employee=request.user, version=version, mode=mode
    )
    return redirect("training_proctor", pk=session.pk)


@employee_required
@never_cache
def proctor_room(request, pk):
    session = proctor.owned_session(request, pk)
    return render(
        request,
        "training/proctor.html",
        {
            "session": session,
            "live_url": reverse("concierge") + "?embed=1&proctor=" + str(session.pk),
            "context": proctor.context(request.user, session.version),
        },
    )


@employee_required
@never_cache
def management(request):
    services.require_manager(request.user)
    content_status = request.GET.get("status", "owner_review")
    if content_status not in dict(ModuleVersion.STATES) and content_status != "all":
        content_status = "owner_review"
    content = (
        ModuleVersion.objects.select_related("module__track")
        .prefetch_related("assets")
        .order_by("module__track_id", "module__position", "-number")
    )
    if content_status != "all":
        content = content.filter(status=content_status)
    return render(
        request,
        "training/management.html",
        {
            "enrollments": CertificationAttempt.objects.select_related(
                "employee", "track"
            ).order_by("-created_at")[:100],
            "employees": get_user_model().objects.filter(
                is_active=True, role__in=["employee", "admin", "owner"]
            ),
            "tracks": Track.objects.filter(is_active=True),
            "drafts": content,
            "content_status": content_status,
            "content_states": ModuleVersion.STATES,
            "owner": request.user.is_owner(),
        },
    )


@employee_required
@never_cache
@require_POST
def assign(request):
    services.require_manager(request.user)
    if not all(request.POST.get(k, "").isdigit() for k in ["employee", "track"]):
        raise Http404()
    employee = get_object_or_404(get_user_model(), pk=request.POST.get("employee"))
    track = get_object_or_404(Track, pk=request.POST.get("track"), is_active=True)
    try:
        enrollment = services.enroll(request.user, employee, track)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("training_management")
    return redirect("training_employee", pk=enrollment.pk)


def _review_attempts(enrollment):
    attempts = list(
        RolePlayAttempt.objects.filter(
            employee=enrollment.employee,
            scenario__version__module__track=enrollment.track,
        )
        .select_related("scenario", "previous")
        .order_by("-created_at")[:30]
    )
    names = dict(Skill.objects.values_list("slug", "title"))
    for attempt in attempts:
        attempt.rubric_rows = [
            {"slug": slug, "title": names.get(slug, slug), "criterion": criterion}
            for slug, criterion in attempt.scenario.rubric.items()
        ]
        if (
            attempt.score is not None
            and attempt.previous
            and attempt.previous.score is not None
        ):
            attempt.improvement = round(attempt.score - attempt.previous.score, 2)
    return attempts


@employee_required
@never_cache
def employee_record(request, pk):
    services.require_manager(request.user)
    enrollment = get_object_or_404(
        CertificationAttempt.objects.select_related("employee", "track"), pk=pk
    )
    states = []
    for version in (
        ModuleVersion.objects.filter(module__track=enrollment.track, status="published")
        .select_related("module__track")
        .order_by("module__position", "module_id")
    ):
        states.append(
            {
                "version": version,
                "state": services.module_state(enrollment.employee, version),
            }
        )
    return render(
        request,
        "training/employee.html",
        {
            "enrollment": enrollment,
            "requirements": services.requirements(enrollment),
            "states": states,
            "attempts": _review_attempts(enrollment),
            "quizzes": QuizAttempt.objects.filter(
                employee=enrollment.employee,
                quiz__version__module__track=enrollment.track,
            )
            .select_related("quiz__version__module")
            .order_by("-created_at")[:50],
            "reviews": enrollment.reviews.select_related("manager").order_by(
                "-created_at"
            )[:30],
            "assignments": enrollment.assignments.select_related(
                "version__module"
            ).order_by("-created_at")[:30],
            "skills": EmployeeSkill.objects.filter(employee=enrollment.employee)
            .select_related("skill", "attempt")
            .order_by("-created_at")[:50],
            "phases": CertificationAttempt.PHASES[:3],
            "owner": request.user.is_owner(),
            "credit_modules": enrollment.track.modules.order_by("position", "pk"),
            "credit_nonce": uuid.uuid4(),
            "transfers": enrollment.transfers.select_related(
                "credited_by", "revoked_by", "through_module"
            )
            .prefetch_related("versions__module")
            .order_by("-created_at"),
        },
    )


@employee_required
@never_cache
@require_POST
def transfer_progress(request, pk):
    if not services.is_owner(request.user):
        raise PermissionDenied("Only the owner can credit prior learning.")
    enrollment = get_object_or_404(CertificationAttempt, pk=pk)
    try:
        if request.POST.get("action") == "undo":
            transfer_id = request.POST.get("transfer", "")
            if not transfer_id.isdigit():
                raise ValidationError("Choose a completion credit to undo.")
            services.undo_progress_transfer(request.user, enrollment, transfer_id)
            messages.success(
                request,
                "Completion credit undone. Recorded playback and attempts are unchanged.",
            )
        elif request.POST.get("action") == "apply":
            transfer = services.transfer_progress(
                request.user,
                enrollment,
                request.POST.get("through"),
                request.POST.get("scope"),
                request.POST.get("note", ""),
                request.POST.get("nonce"),
            )
            messages.success(
                request,
                f"{transfer.get_scope_display()} credited for {transfer.versions.count()} modules. The learning path is updated.",
            )
        else:
            raise ValidationError("Choose a completion action.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("training_employee", pk=pk)


@employee_required
@never_cache
@require_POST
def manager_action(request, pk):
    services.require_manager(request.user)
    enrollment = get_object_or_404(
        CertificationAttempt.objects.select_related("employee", "track"), pk=pk
    )
    action = request.POST.get("action")
    note = request.POST.get("note", "").strip()
    try:
        if not note or len(note) > 3000:
            raise ValidationError("Add a review note of 1–3,000 characters.")
        if action == "certify":
            services.certify(request.user, enrollment, note)
        elif action == "revoke":
            services.revoke(request.user, enrollment, note)
        elif action == "retrain":
            if not request.POST.get("version", "").isdigit():
                raise ValidationError("Choose a published module.")
            version = get_object_or_404(
                ModuleVersion,
                pk=request.POST.get("version"),
                module__track=enrollment.track,
            )
            due = (
                parse_date(request.POST.get("due", ""))
                if request.POST.get("due")
                else None
            )
            services.assign_retraining(request.user, enrollment, version, note, due)
        elif action == "phase":
            phase = request.POST.get("phase")
            if phase not in dict(CertificationAttempt.PHASES[:3]):
                raise ValidationError(
                    "Certification is required for independent status."
                )
            if enrollment.certifications.filter(revoked_at__isnull=True).exists():
                services.revoke(request.user, enrollment, note)
            enrollment.phase = phase
            enrollment.save(update_fields=["phase"])
        elif action == "practical":
            ManagerReview.objects.create(
                enrollment=enrollment,
                manager=request.user,
                kind="practical",
                passed=request.POST.get("passed") == "on",
                crm_practical=request.POST.get("crm_practical") == "on",
                note=note,
            )
        elif action == "roleplay":
            with transaction.atomic():
                attempt_id = uuid.UUID(request.POST.get("attempt", ""))
                attempt = get_object_or_404(
                    RolePlayAttempt.objects.select_for_update(),
                    pk=attempt_id,
                    employee=enrollment.employee,
                    scenario__version__module__track=enrollment.track,
                    state="review",
                )
                scores = {
                    slug: float(request.POST.get("score_" + slug, ""))
                    for slug in attempt.scenario.rubric
                }
                if not isinstance(scores, dict) or set(scores) != set(
                    attempt.scenario.rubric
                ):
                    raise ValidationError(
                        "Supply one score for every skill shown in the scenario rubric."
                    )
                if not scores or any(
                    type(s) not in (int, float)
                    or not math.isfinite(s)
                    or not 1 <= s <= 10
                    for s in scores.values()
                ):
                    raise ValidationError("Scores must be numbers from 1–10.")
                critical = [
                    s.strip()
                    for s in request.POST.get("critical", "").splitlines()
                    if s.strip()
                ]
                if len(critical) > 20 or any(len(c) > 500 for c in critical):
                    raise ValidationError("Keep critical failure notes concise.")
                attempt.score = round(sum(scores.values()) / len(scores), 2)
                attempt.critical_failures = critical
                attempt.state = "reviewed"
                attempt.feedback = {
                    "manager": request.user.get_full_name() or request.user.username,
                    "note": note,
                    "scores": scores,
                }
                attempt.save()
                review = ManagerReview.objects.create(
                    enrollment=enrollment,
                    manager=request.user,
                    roleplay=attempt,
                    kind="roleplay",
                    passed=not critical
                    and attempt.score >= enrollment.track.roleplay_pass_score,
                    note=note,
                    evidence={"scores": scores, "critical_failures": critical},
                )
                for slug, score in scores.items():
                    skill = get_object_or_404(Skill, slug=slug)
                    EmployeeSkill.objects.create(
                        employee=enrollment.employee,
                        skill=skill,
                        attempt=attempt,
                        score=score,
                        evidence=note,
                        source="manager_review",
                    )
        else:
            raise ValidationError("Choose a training action.")
        messages.success(request, "Training record updated.")
    except (ValueError, TypeError):
        messages.error(request, "Check the date and skill scores.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("training_employee", pk=enrollment.pk)


@employee_required
@never_cache
@require_POST
def publication(request, pk):
    version = get_object_or_404(ModuleVersion, pk=pk)
    quick_approval = request.POST.get("status") == "approve_publish"
    try:
        if quick_approval:
            services.approve_and_publish(request.user, version)
        else:
            services.transition(request.user, version, request.POST.get("status"))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(
            request,
            (
                f"{version.module.title} is approved and published. Assigned employees can start learning."
                if quick_approval
                else "Content state updated."
            ),
        )
    if request.POST.get("return_to") == "management":
        return redirect("training_management")
    return redirect("training_lesson", pk=pk)


@employee_required
@never_cache
def history(request):
    from django.core.paginator import Paginator
    from .models import Certification

    quizzes = (
        QuizAttempt.objects.filter(employee=request.user)
        .select_related("quiz__version__module")
        .order_by("-created_at")
    )
    attempts = (
        RolePlayAttempt.objects.filter(employee=request.user)
        .select_related("scenario__version__module")
        .order_by("-created_at")
    )
    return render(
        request,
        "training/history.html",
        {
            "quizzes": Paginator(quizzes, 20).get_page(request.GET.get("quiz_page")),
            "attempts": Paginator(attempts, 20).get_page(
                request.GET.get("practice_page")
            ),
            "certifications": Certification.objects.filter(
                enrollment__employee=request.user
            )
            .select_related("enrollment__track", "review")
            .order_by("-awarded_at"),
            "transfers": ProgressTransfer.objects.filter(
                enrollment__employee=request.user
            )
            .select_related("enrollment__track", "credited_by", "through_module")
            .prefetch_related("versions__module")
            .order_by("-created_at"),
        },
    )


@employee_required
@never_cache
@require_POST
def revision(request, pk):
    version = get_object_or_404(ModuleVersion, pk=pk)
    try:
        new = services.clone_version(request.user, version)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("training_lesson", pk=pk)
    messages.success(
        request,
        "New draft created. Edit its content in the content administration screen; review the video and captions again before approval.",
    )
    return redirect("training_lesson", pk=new.pk)
