import math
import uuid
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone
from .models import (
    Module,
    ModuleVersion,
    EmployeeProgress,
    QuizAttempt,
    RolePlayAttempt,
    CertificationAttempt,
    TrainingAssignment,
    ManagerReview,
    Certification,
)


def is_manager(user):
    return user.is_authenticated and (
        user.is_superuser or user.role in {"admin", "owner"}
    )


def require_manager(user):
    if not is_manager(user):
        raise PermissionDenied("Training manager access required.")


def is_owner(user):
    return user.is_authenticated and user.is_owner()


def can_preview_locally(user, version):
    """Allow explicitly permitted, enrolled employees to watch local review films."""
    return bool(
        settings.DEBUG
        and connection.vendor == "sqlite"
        and user.is_authenticated
        and user.is_active
        and user.is_employee_or_admin()
        and user.has_perm("training.view_moduleversion")
        and version.status == "owner_review"
        and version.module.track.is_active
        and version.assets.filter(kind="video").exists()
        and CertificationAttempt.objects.filter(
            employee=user, track=version.module.track
        ).exists()
    )


def can_learn(user, version):
    return (
        ModuleVersion.objects.filter(
            pk=version.pk, status="published", module__track__is_active=True
        ).exists()
        and CertificationAttempt.objects.filter(
            employee=user, track=version.module.track
        ).exists()
    )


def require_learning(user, version):
    if not can_learn(user, version):
        raise PermissionDenied(
            "This version must be published and the track assigned before recording learning evidence."
        )


def watched(progress):
    return sum(end - start for start, end in progress.watched_ranges) if progress else 0


def merge_ranges(ranges):
    output = []
    for start, end in sorted(ranges):
        if output and start <= output[-1][1] + 0.25:
            output[-1][1] = max(output[-1][1], end)
        else:
            output.append([start, end])
    return output


@transaction.atomic
def heartbeat(user, version, data):
    require_learning(user, version)
    type(user).objects.select_for_update().get(pk=user.pk)
    progress = (
        EmployeeProgress.objects.filter(employee=user, version=version)
        .order_by("-cycle")
        .first()
    )
    if not progress:
        progress = EmployeeProgress.objects.create(employee=user, version=version)
    progress = EmployeeProgress.objects.select_for_update().get(pk=progress.pk)
    try:
        start = float(data.get("start", 0))
        end = float(data["position"])
        sid = uuid.UUID(str(data["session"]))
    except (ValueError, TypeError, KeyError):
        raise ValidationError("Invalid playback update.")
    if not all(
        math.isfinite(n) and 0 <= n <= version.duration_seconds for n in [start, end]
    ):
        raise ValidationError("Invalid playback position.")
    now = timezone.now()
    if (
        progress.last_ping
        and progress.watch_session == sid
        and data.get("playing") is True
    ):
        elapsed = (now - progress.last_ping).total_seconds()
        delta = end - start
        # Only contiguous playback within a recent server-observed heartbeat window earns credit.
        if (
            0 < elapsed <= 35
            and 0 < delta <= min(45, elapsed * 2.25 + 1)
            and abs(start - progress.position_seconds) < 1.5
        ):
            progress.watched_ranges = merge_ranges(
                progress.watched_ranges + [[start, end]]
            )
            progress.active_seconds += min(elapsed, delta)
    progress.position_seconds = end
    progress.last_ping = now
    progress.watch_session = sid
    if (
        watched(progress)
        >= version.duration_seconds * version.module.track.watch_percent / 100
        and not progress.completed_at
    ):
        progress.completed_at = now
    progress.save()
    return progress


@transaction.atomic
def submit_quiz(user, quiz, answers, nonce):
    require_learning(user, quiz.version)
    try:
        nonce = uuid.UUID(str(nonce))
    except (ValueError, TypeError):
        raise ValidationError("Reload the quiz before submitting.")
    # Per-employee lock makes double-click/retry safe even on different workers.
    type(user).objects.select_for_update().get(pk=user.pk)
    old = QuizAttempt.objects.filter(employee=user, nonce=nonce).first()
    if old:
        if old.quiz_id != quiz.pk:
            raise ValidationError("This submission belongs to another quiz.")
        return old
    questions = list(quiz.questions.all())
    if (
        not questions
        or not isinstance(answers, dict)
        or set(answers) != set(str(q.pk) for q in questions)
    ):
        raise ValidationError("Answer every question once.")
    feedback = []
    correct = 0
    for q in questions:
        answer = answers[str(q.pk)]
        if type(answer) is not int or not 0 <= answer < len(q.choices):
            raise ValidationError("Choose an available answer.")
        ok = answer == q.correct_index
        correct += ok
        feedback.append(
            {
                "question": q.prompt,
                "selected": q.choices[answer],
                "correct": q.choices[q.correct_index],
                "is_correct": ok,
                "explanation": q.explanation,
            }
        )
    score = round(100 * correct / len(questions), 2)
    threshold = quiz.version.module.track.quiz_pass_percent
    return QuizAttempt.objects.create(
        employee=user,
        quiz=quiz,
        nonce=nonce,
        answers=answers,
        feedback=feedback,
        score=score,
        pass_percent=threshold,
        passed=score >= threshold,
    )


def module_state(user, version, since=None):
    if since is None:
        assignment = (
            TrainingAssignment.objects.filter(
                enrollment__employee=user, version=version, active=True, retraining=True
            )
            .order_by("-created_at")
            .first()
        )
        since = assignment.created_at if assignment else None
    progress = (
        EmployeeProgress.objects.filter(employee=user, version=version)
        .order_by("-cycle")
        .first()
    )
    video = bool(
        progress
        and progress.completed_at
        and watched(progress)
        >= version.duration_seconds * version.module.track.watch_percent / 100
        and (not since or progress.completed_at >= since)
    )
    quizzes = QuizAttempt.objects.filter(
        employee=user,
        quiz__version=version,
        score__gte=version.module.track.quiz_pass_percent,
    )
    if since:
        quizzes = quizzes.filter(created_at__gte=since)
    quiz = quizzes.exists() if hasattr(version, "quiz") else False
    required = version.scenarios.filter(required=True)
    practice = True
    for scenario in required:
        attempts = RolePlayAttempt.objects.filter(
            employee=user,
            scenario=scenario,
            state="reviewed",
            score__gte=version.module.track.roleplay_pass_score,
            critical_failures=[],
        )
        if since:
            attempts = attempts.filter(created_at__gte=since)
        if not attempts.exists():
            practice = False
    complete = version.status == "published" and video and quiz and practice
    if since and not complete:
        label = "Retraining required"
    elif complete:
        label = "Complete"
    elif not video:
        label = "In progress" if progress and watched(progress) > 0 else "Not started"
    elif not quiz:
        label = "Quiz required"
    elif not practice:
        label = "Practice / manager review required"
    else:
        label = "Video complete"
    return {
        "video": video,
        "quiz": quiz,
        "practice": practice,
        "complete": complete,
        "label": label,
        "percent": min(100, round(100 * watched(progress) / version.duration_seconds)),
        "position": progress.position_seconds if progress else 0,
        "active_seconds": round(progress.active_seconds) if progress else 0,
    }


def requirements(enrollment):
    gaps = []
    evidence = []
    versions = []
    modules = list(enrollment.track.modules.filter(required=True))
    if not modules:
        gaps.append("This track has no required modules.")
    for module in modules:
        assignment = (
            enrollment.assignments.filter(version__module=module, active=True)
            .select_related("version")
            .order_by("-created_at")
            .first()
        )
        version = (
            assignment.version
            if assignment
            else module.versions.filter(status="published").order_by("-number").first()
        )
        if not version or version.status != "published":
            gaps.append(f"{module.title}: published training required.")
            continue
        versions.append(version)
        state = module_state(
            enrollment.employee,
            version,
            assignment.created_at if assignment and assignment.retraining else None,
        )
        evidence.append(
            {
                "module": module.pk,
                "version": version.pk,
                "number": version.number,
                "state": state,
            }
        )
        if not state["complete"]:
            gaps.append(f'{module.title}: {state["label"]}.')
    capstone = (
        RolePlayAttempt.objects.filter(
            employee=enrollment.employee,
            scenario__version__in=versions,
            scenario__capstone=True,
            state="reviewed",
            score__gte=enrollment.track.roleplay_pass_score,
            critical_failures=[],
        )
        .order_by("-created_at")
        .first()
    )
    if not capstone:
        gaps.append("A manager-reviewed passing capstone is required.")
    last_retrain = (
        enrollment.assignments.filter(active=True, retraining=True)
        .order_by("-created_at")
        .first()
    )
    practical = (
        enrollment.reviews.filter(kind="practical").order_by("-created_at").first()
    )
    if (
        not practical
        or not practical.passed
        or not practical.crm_practical
        or (last_retrain and practical.created_at < last_retrain.created_at)
    ):
        gaps.append(
            "A current manager-reviewed mock/practical call and CRM practical are required."
        )
    return {
        "gaps": gaps,
        "modules": evidence,
        "quiz_pass_percent": enrollment.track.quiz_pass_percent,
        "roleplay_pass_score": enrollment.track.roleplay_pass_score,
        "watch_percent": enrollment.track.watch_percent,
        "practical_review": practical.pk if practical else None,
        "capstone": str(capstone.pk) if capstone else None,
    }


@transaction.atomic
def enroll(manager, employee, track):
    require_manager(manager)
    if not employee.is_active or not employee.is_employee_or_admin():
        raise ValidationError("Choose an active employee.")
    enrollment, _ = CertificationAttempt.objects.get_or_create(
        employee=employee, track=track, defaults={"assigned_by": manager}
    )
    for module in track.modules.all():
        version = module.versions.filter(status="published").order_by("-number").first()
        if (
            version
            and not enrollment.assignments.filter(
                version__module=module, active=True
            ).exists()
        ):
            TrainingAssignment.objects.create(
                enrollment=enrollment, version=version, assigned_by=manager
            )
    return enrollment


@transaction.atomic
def assign_retraining(manager, enrollment, version, note, due_at=None):
    require_manager(manager)
    enrollment = CertificationAttempt.objects.select_for_update().get(pk=enrollment.pk)
    if version.module.track_id != enrollment.track_id or version.status != "published":
        raise ValidationError("Assign a published version from this track.")
    if not note.strip():
        raise ValidationError("Explain the retraining focus.")
    enrollment.assignments.filter(version__module=version.module, active=True).update(
        active=False
    )
    assignment = TrainingAssignment.objects.create(
        enrollment=enrollment,
        version=version,
        assigned_by=manager,
        note=note[:3000],
        due_at=due_at,
        retraining=True,
    )
    type(enrollment.employee).objects.select_for_update().get(pk=enrollment.employee_id)
    previous = (
        EmployeeProgress.objects.filter(employee=enrollment.employee, version=version)
        .order_by("-cycle")
        .first()
    )
    EmployeeProgress.objects.create(
        employee=enrollment.employee,
        version=version,
        cycle=previous.cycle + 1 if previous else 1,
    )
    revoke(manager, enrollment, "Retraining assigned: " + note[:2500])
    return assignment


@transaction.atomic
def revoke(manager, enrollment, note):
    require_manager(manager)
    enrollment = CertificationAttempt.objects.select_for_update().get(pk=enrollment.pk)
    enrollment.certifications.filter(revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    enrollment.phase = "supervised"
    enrollment.save(update_fields=["phase"])
    return ManagerReview.objects.create(
        enrollment=enrollment, manager=manager, kind="revoke", note=note[:3000]
    )


@transaction.atomic
def certify(manager, enrollment, note):
    require_manager(manager)
    enrollment = CertificationAttempt.objects.select_for_update().get(pk=enrollment.pk)
    snapshot = requirements(enrollment)
    if snapshot["gaps"]:
        raise ValidationError(snapshot["gaps"])
    if not note.strip():
        raise ValidationError("Record the basis for manager approval.")
    if enrollment.certifications.filter(revoked_at__isnull=True).exists():
        raise ValidationError("This employee is already certified.")
    review = ManagerReview.objects.create(
        enrollment=enrollment,
        manager=manager,
        kind="certify",
        passed=True,
        note=note[:3000],
        evidence=snapshot,
    )
    award = Certification.objects.create(
        enrollment=enrollment, review=review, requirements_snapshot=snapshot
    )
    enrollment.phase = "independent"
    enrollment.save(update_fields=["phase"])
    return award


@transaction.atomic
def transition(user, version, target):
    if not is_owner(user):
        raise PermissionDenied("Only the owner can approve and publish training.")
    Module.objects.select_for_update().get(pk=version.module_id)
    version = ModuleVersion.objects.select_for_update().get(pk=version.pk)
    allowed = {
        "draft": {"owner_review"},
        "owner_review": {"draft", "approved"},
        "approved": {"published"},
        "published": {"retired"},
        "retired": set(),
    }
    if target not in allowed[version.status]:
        raise ValidationError("Invalid content transition.")
    if target == "approved":
        if (
            not version.transcript.strip()
            or not hasattr(version, "quiz")
            or not version.quiz.questions.exists()
        ):
            raise ValidationError("Provide the complete lesson and quiz first.")
        if not {"video", "captions"} <= set(
            version.assets.filter(reviewed=True).values_list("kind", flat=True)
        ):
            raise ValidationError(
                "The owner must review the finished video and captions before final content approval. Written-package review alone does not publish a lesson."
            )
        from .media import validate_key

        for asset in version.assets.all():
            validate_key(asset.storage_key)
        for question in version.quiz.questions.all():
            question.full_clean()
        version.approved_by = user
        version.approved_at = timezone.now()
    if target == "published":
        from .media import configured

        if not configured():
            raise ValidationError(
                "Configure private durable training media before publication."
            )
        if version.module.versions.filter(status="published").exists():
            raise ValidationError("Retire the previous published version first.")
        version.published_at = timezone.now()
    if target == "retired":
        version.retired_at = timezone.now()
    version.status = target
    version._transition = True
    version.save()
    return version


@transaction.atomic
def approve_and_publish(user, version):
    """The owner's single click accepts the current assets and releases the lesson."""
    if not is_owner(user):
        raise PermissionDenied("Only the owner can approve and publish training.")
    Module.objects.select_for_update().get(pk=version.module_id)
    version = ModuleVersion.objects.select_for_update().get(pk=version.pk)
    if version.status == "published":
        return version
    if version.status == "retired":
        raise ValidationError(
            "Create a new draft revision to release a retired lesson."
        )
    if not version.has_review_media:
        raise ValidationError(
            "Attach the finished video and captions before approving this lesson."
        )
    if version.status == "draft":
        version = transition(user, version, "owner_review")
    if version.status == "owner_review":
        for asset in version.assets.select_for_update():
            asset.reviewed = True
            asset.save(update_fields=["reviewed"])
        version = transition(user, version, "approved")
    return transition(user, version, "published")


@transaction.atomic
def clone_version(user, version):
    """Preserve published evidence; all copied media must be reviewed again."""
    from .models import Module, LessonAsset, Quiz, Question, RolePlayScenario

    if not is_owner(user):
        raise PermissionDenied("Only the owner can create content revisions.")
    Module.objects.select_for_update().get(pk=version.module_id)
    latest = version.module.versions.order_by("-number").first()
    if latest.status in {"draft", "owner_review"} and latest.pk != version.pk:
        raise ValidationError(
            "Finish the existing draft revision before creating another."
        )
    new = ModuleVersion.objects.create(
        module=version.module,
        number=latest.number + 1,
        policy_version=version.policy_version,
        summary=version.summary,
        transcript=version.transcript,
        scenes=version.scenes,
        job_aid=version.job_aid,
        duration_seconds=version.duration_seconds,
    )
    for asset in version.assets.all():
        LessonAsset.objects.create(
            version=new, kind=asset.kind, storage_key=asset.storage_key, reviewed=False
        )
    if hasattr(version, "quiz"):
        quiz = Quiz.objects.create(version=new, title=version.quiz.title)
        for q in version.quiz.questions.all():
            Question.objects.create(
                quiz=quiz,
                prompt=q.prompt,
                choices=q.choices,
                correct_index=q.correct_index,
                explanation=q.explanation,
                position=q.position,
                skill=q.skill,
            )
    for scenario in version.scenarios.all():
        RolePlayScenario.objects.create(
            version=new,
            **{
                k: getattr(scenario, k)
                for k in [
                    "title",
                    "persona",
                    "opening",
                    "rubric",
                    "difficulty",
                    "required",
                    "capstone",
                ]
            },
        )
    return new
