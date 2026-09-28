import json
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from .models import *
from . import services, proctor


@override_settings(TRAINING_S3_BUCKET="private-test-bucket", PLATFORM_OPENAI_API_KEY="")
class AcademyTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="academy-owner", role="owner")
        self.rep = User.objects.create_user(username="academy-rep", role="employee")
        self.other = User.objects.create_user(username="academy-other", role="employee")
        self.customer = User.objects.create_user(
            username="academy-customer", role="client"
        )
        self.course = Course.objects.create(title="Academy", slug="academy")
        self.track = Track.objects.create(
            course=self.course, title="Core", slug="core", kind="core"
        )
        self.module = Module.objects.create(
            track=self.track, title="Mission", slug="mission", position=1
        )
        self.version = ModuleVersion.objects.create(
            module=self.module,
            transcript="The human specialist conducts the assessment.",
            summary="Problem first",
            duration_seconds=100,
        )
        self.quiz = Quiz.objects.create(version=self.version)
        self.question = Question.objects.create(
            quiz=self.quiz,
            prompt="What follows a request to stop?",
            choices=["Stop and record it", "Keep calling"],
            correct_index=0,
            explanation="Respect contact restrictions.",
        )
        self.skill = Skill.objects.create(slug="listening", title="Listening")
        self.scenario = RolePlayScenario.objects.create(
            version=self.version,
            title="Listen first",
            persona="Fictional owner",
            opening="How can I help?",
            rubric={"listening": "Follow the answer"},
            capstone=True,
        )
        LessonAsset.objects.create(
            version=self.version,
            kind="video",
            storage_key="training/v1/lesson.mp4",
            reviewed=True,
        )
        LessonAsset.objects.create(
            version=self.version,
            kind="captions",
            storage_key="training/v1/captions.vtt",
            reviewed=True,
        )
        self.enrollment = services.enroll(self.owner, self.rep, self.track)
        self.client.force_login(self.rep)

    def publish(self, version=None):
        version = version or self.version
        for state in ["owner_review", "approved", "published"]:
            version = services.transition(self.owner, version, state)
        self.version.refresh_from_db()
        return version

    def complete_evidence(self):
        self.publish()
        EmployeeProgress.objects.create(
            employee=self.rep,
            version=self.version,
            watched_ranges=[[0, 100]],
            completed_at=timezone.now(),
        )
        services.submit_quiz(
            self.rep, self.quiz, {str(self.question.pk): 0}, uuid.uuid4()
        )
        attempt = RolePlayAttempt.objects.create(
            employee=self.rep,
            scenario=self.scenario,
            state="reviewed",
            score=9,
            handoff="Facts and hypothesis separated.",
        )
        ManagerReview.objects.create(
            enrollment=self.enrollment,
            manager=self.owner,
            kind="roleplay",
            passed=True,
            roleplay=attempt,
            note="Observed questions and accurate handoff.",
        )
        ManagerReview.objects.create(
            enrollment=self.enrollment,
            manager=self.owner,
            kind="practical",
            passed=True,
            crm_practical=True,
            note="Mock call and CRM handoff observed.",
        )
        return attempt

    def test_permissions_and_private_manager_records(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("training_home")).status_code, 302)
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(reverse("training_home")).status_code, 302)
        self.client.force_login(self.rep)
        self.assertEqual(self.client.get(reverse("training_home")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("training_management")).status_code, 403
        )
        self.assertEqual(
            self.client.get(
                reverse("training_employee", args=[self.enrollment.pk])
            ).status_code,
            403,
        )
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(
                reverse("training_employee", args=[self.enrollment.pk])
            ).status_code,
            200,
        )

    def test_drafts_cannot_be_accessed_as_active_lessons_or_earn_credit(self):
        self.assertEqual(
            self.client.get(
                reverse("training_lesson", args=[self.version.pk])
            ).status_code,
            403,
        )
        with self.assertRaises(PermissionDenied):
            services.submit_quiz(
                self.rep, self.quiz, {str(self.question.pk): 0}, uuid.uuid4()
            )
        with self.assertRaises(PermissionDenied):
            services.heartbeat(
                self.rep, self.version, {"position": 100, "session": str(uuid.uuid4())}
            )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("training_lesson", args=[self.version.pk]))
        self.assertContains(response, "OWNER REVIEW PREVIEW")
        self.assertContains(response, "disabled")
        self.assertTrue(services.requirements(self.enrollment)["gaps"])

    def test_published_lessons_require_track_assignment(self):
        self.publish()
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(
                reverse("training_lesson", args=[self.version.pk])
            ).status_code,
            403,
        )
        services.enroll(self.owner, self.other, self.track)
        self.assertEqual(
            self.client.get(
                reverse("training_lesson", args=[self.version.pk])
            ).status_code,
            200,
        )

    @override_settings(DEBUG=True)
    def test_explicit_local_preview_allows_watching_without_learning_credit(self):
        from django.contrib.auth.models import Permission

        self.version = services.transition(self.owner, self.version, "owner_review")
        permission = Permission.objects.get(
            content_type__app_label="training", codename="view_moduleversion"
        )
        self.assertFalse(services.can_preview_locally(self.rep, self.version))
        self.rep.user_permissions.add(permission)
        self.rep = get_user_model().objects.get(pk=self.rep.pk)
        self.assertTrue(services.can_preview_locally(self.rep, self.version))
        self.assertFalse(services.can_learn(self.rep, self.version))
        home = self.client.get(reverse("training_home"))
        self.assertContains(home, "Local preview · watch now")
        self.assertContains(home, reverse("training_lesson", args=[self.version.pk]))
        lesson = self.client.get(reverse("training_lesson", args=[self.version.pk]))
        self.assertContains(lesson, "LOCAL LEARNING PREVIEW")
        self.assertContains(lesson, 'data-official="false"')
        self.assertContains(lesson, "disabled")
        self.assertNotContains(lesson, "Manage this lesson")
        with patch(
            "training.media.media_url", return_value="https://example.com/video"
        ):
            self.assertEqual(
                self.client.get(
                    reverse("training_asset", args=[self.version.pk, "video"])
                ).status_code,
                302,
            )
        with self.assertRaises(PermissionDenied):
            services.heartbeat(self.rep, self.version, {})
        with self.assertRaises(PermissionDenied):
            services.submit_quiz(self.rep, self.quiz, {}, uuid.uuid4())
        self.assertFalse(EmployeeProgress.objects.filter(employee=self.rep).exists())
        self.assertEqual(
            self.client.get(reverse("training_management")).status_code, 403
        )
        with override_settings(DEBUG=False):
            self.assertFalse(services.can_preview_locally(self.rep, self.version))
            self.assertEqual(
                self.client.get(
                    reverse("training_lesson", args=[self.version.pk])
                ).status_code,
                403,
            )
        with patch("training.services.connection.vendor", "postgresql"):
            self.assertFalse(services.can_preview_locally(self.rep, self.version))
        self.other.user_permissions.add(permission)
        self.assertFalse(services.can_preview_locally(self.other, self.version))
        draft = ModuleVersion.objects.create(module=self.module, number=2)
        self.assertFalse(services.can_preview_locally(self.rep, draft))

    def test_only_owner_can_approve_and_publish(self):
        with self.assertRaises(PermissionDenied):
            services.transition(self.rep, self.version, "owner_review")
        admin = get_user_model().objects.create_user(
            username="academy-admin", role="admin"
        )
        with self.assertRaises(PermissionDenied):
            services.transition(admin, self.version, "owner_review")
        with self.assertRaises(ValidationError):
            services.transition(self.owner, self.version, "published")
        self.version = services.transition(self.owner, self.version, "owner_review")
        self.version.assets.filter(kind="video").update(reviewed=False)
        with self.assertRaises(ValidationError):
            services.transition(self.owner, self.version, "approved")

    def test_one_click_approval_publishes_and_records_the_owner_once(self):
        self.version = services.transition(self.owner, self.version, "owner_review")
        self.version.assets.update(reviewed=False)
        self.client.force_login(self.owner)
        for url in [
            reverse("training_lesson", args=[self.version.pk]),
            reverse("training_management"),
        ]:
            self.assertContains(self.client.get(url), "Approve &amp; publish")
        response = self.client.post(
            reverse("training_publication", args=[self.version.pk]),
            {"status": "approve_publish"},
            follow=True,
        )
        self.assertContains(response, "Approved &amp; published")
        self.assertNotContains(response, "OWNER REVIEW PREVIEW")
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, "published")
        self.assertEqual(self.version.approved_by, self.owner)
        self.assertFalse(self.version.assets.filter(reviewed=False).exists())
        original_times = (self.version.approved_at, self.version.published_at)
        services.approve_and_publish(self.owner, self.version)
        self.version.refresh_from_db()
        self.assertEqual(
            original_times, (self.version.approved_at, self.version.published_at)
        )
        self.assertTrue(services.can_learn(self.rep, self.version))
        self.assertFalse(EmployeeProgress.objects.exists())

    def test_one_click_approval_rejects_missing_media_without_mutation(self):
        self.version.assets.filter(kind="captions").delete()
        self.version.assets.update(reviewed=False)
        with self.assertRaises(ValidationError):
            services.approve_and_publish(self.owner, self.version)
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, "draft")
        self.assertIsNone(self.version.approved_at)
        self.assertFalse(self.version.assets.filter(reviewed=True).exists())

    def test_one_click_approval_rolls_back_review_on_invalid_quiz_or_storage(self):
        self.version.assets.update(reviewed=False)
        self.question.correct_index = 10
        self.question.save()
        with self.assertRaises(ValidationError):
            services.approve_and_publish(self.owner, self.version)
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, "draft")
        self.assertFalse(self.version.assets.filter(reviewed=True).exists())
        self.question.correct_index = 0
        self.question.save()
        with override_settings(TRAINING_S3_BUCKET="", TRAINING_MEDIA_ROOT=""):
            with self.assertRaises(ValidationError):
                services.approve_and_publish(self.owner, self.version)
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, "draft")
        self.assertIsNone(self.version.approved_by)
        self.assertFalse(self.version.assets.filter(reviewed=True).exists())

    def test_one_click_approval_is_owner_only_and_requires_post(self):
        endpoint = reverse("training_publication", args=[self.version.pk])
        admin = get_user_model().objects.create_user(
            username="approval-admin", role="admin"
        )
        for user in [self.rep, admin]:
            self.client.force_login(user)
            self.assertEqual(
                self.client.post(endpoint, {"status": "approve_publish"}).status_code,
                403,
            )
        self.client.force_login(admin)
        self.assertNotContains(
            self.client.get(reverse("training_lesson", args=[self.version.pk])),
            "Approve &amp; publish",
        )
        self.assertNotContains(
            self.client.get(reverse("training_management")), "Approve &amp; publish"
        )
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(endpoint).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        self.assertEqual(
            csrf_client.post(endpoint, {"status": "approve_publish"}).status_code, 403
        )
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, "draft")

    def test_one_click_approval_supports_approved_content_and_catalog_return(self):
        for state in ["owner_review", "approved"]:
            self.version = services.transition(self.owner, self.version, state)
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("training_publication", args=[self.version.pk]),
            {"status": "approve_publish", "return_to": "management"},
        )
        self.assertRedirects(response, reverse("training_management"))
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, "published")

    def test_one_click_approval_preserves_published_and_retired_versions(self):
        self.publish()
        revision = services.clone_version(self.owner, self.version)
        with self.assertRaises(ValidationError):
            services.approve_and_publish(self.owner, revision)
        revision.refresh_from_db()
        self.assertEqual(revision.status, "draft")
        self.assertFalse(revision.assets.filter(reviewed=True).exists())
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, "published")
        self.version = services.transition(self.owner, self.version, "retired")
        with self.assertRaises(ValidationError):
            services.approve_and_publish(self.owner, self.version)

    def test_publication_requires_durable_media_configuration(self):
        self.version = services.transition(self.owner, self.version, "owner_review")
        self.version = services.transition(self.owner, self.version, "approved")
        with override_settings(TRAINING_S3_BUCKET="", TRAINING_MEDIA_ROOT=""):
            with self.assertRaises(ValidationError):
                services.transition(self.owner, self.version, "published")

    def test_approved_versions_and_questions_are_immutable(self):
        self.publish()
        self.version.transcript = "Changed policy"
        with self.assertRaises(ValidationError):
            self.version.save()
        self.question.quiz.refresh_from_db()
        self.question.prompt = "Changed answer"
        with self.assertRaises(ValidationError):
            self.question.save()
        draft = ModuleVersion.objects.create(module=self.module, number=2)
        fresh_quiz = Quiz.objects.create(version=draft)
        self.question.quiz = fresh_quiz
        with self.assertRaises(ValidationError):
            self.question.save()
        self.version.refresh_from_db()
        self.version.status = "draft"
        with self.assertRaises(ValidationError):
            self.version.save()

    def test_quiz_grading_retry_history_and_configurable_threshold(self):
        self.publish()
        fail = services.submit_quiz(
            self.rep, self.quiz, {str(self.question.pk): 1}, uuid.uuid4()
        )
        nonce = uuid.uuid4()
        passed = services.submit_quiz(
            self.rep, self.quiz, {str(self.question.pk): 0}, nonce
        )
        retry = services.submit_quiz(
            self.rep, self.quiz, {str(self.question.pk): 1}, nonce
        )
        self.assertFalse(fail.passed)
        self.assertEqual(passed.pk, retry.pk)
        self.assertTrue(passed.passed)
        self.assertEqual(QuizAttempt.objects.count(), 2)
        self.assertEqual(
            fail.feedback[0]["explanation"], "Respect contact restrictions."
        )
        self.assertEqual(passed.pass_percent, 80)
        self.track.quiz_pass_percent = 95
        self.track.save()
        self.version.module.track.refresh_from_db()
        new = services.submit_quiz(
            self.rep, self.quiz, {str(self.question.pk): 0}, uuid.uuid4()
        )
        self.assertEqual(new.pass_percent, 95)
        passed.refresh_from_db()
        self.assertEqual(passed.pass_percent, 80)

    def test_quiz_rejects_missing_extra_out_of_range_and_boolean_answers(self):
        self.publish()
        for answers in [
            {},
            {str(self.question.pk): 99},
            {str(self.question.pk): True},
            {str(self.question.pk): 0, "999": 0},
            [],
        ]:
            with self.assertRaises(ValidationError):
                services.submit_quiz(self.rep, self.quiz, answers, uuid.uuid4())
        self.assertEqual(QuizAttempt.objects.count(), 0)

    def test_answer_key_not_exposed_before_submission(self):
        self.publish()
        response = self.client.get(reverse("training_lesson", args=[self.version.pk]))
        self.assertNotContains(response, "Respect contact restrictions.")
        self.assertNotContains(response, "correct_index")

    def test_csrf_and_post_only(self):
        self.publish()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.rep)
        self.assertEqual(
            client.post(
                reverse("training_quiz", args=[self.version.pk]),
                data="{}",
                content_type="application/json",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                reverse("training_progress", args=[self.version.pk])
            ).status_code,
            405,
        )

    def test_watch_progress_requires_elapsed_contiguous_playback(self):
        self.publish()
        sid = str(uuid.uuid4())
        now = timezone.now()
        with patch("training.services.timezone.now", return_value=now):
            services.heartbeat(
                self.rep, self.version, {"position": 0, "session": sid, "playing": True}
            )
        self.assertEqual(services.module_state(self.rep, self.version)["percent"], 0)
        with patch(
            "training.services.timezone.now", return_value=now + timedelta(seconds=10)
        ):
            p = services.heartbeat(
                self.rep,
                self.version,
                {"start": 0, "position": 90, "session": sid, "playing": True},
            )
        self.assertEqual(services.watched(p), 0)
        with patch(
            "training.services.timezone.now", return_value=now + timedelta(seconds=20)
        ):
            p = services.heartbeat(
                self.rep,
                self.version,
                {"start": 90, "position": 100, "session": sid, "playing": True},
            )
        self.assertEqual(services.watched(p), 10)
        self.assertFalse(p.completed_at)

    def test_unique_ranges_do_not_double_count_replays_and_nan_is_rejected(self):
        self.publish()
        self.assertEqual(
            services.merge_ranges([[0, 20], [10, 30], [50, 60]]), [[0, 30], [50, 60]]
        )
        with self.assertRaises(ValidationError):
            services.heartbeat(
                self.rep,
                self.version,
                {"position": float("nan"), "session": str(uuid.uuid4())},
            )

    def test_certification_is_not_video_completion(self):
        self.publish()
        EmployeeProgress.objects.create(
            employee=self.rep,
            version=self.version,
            watched_ranges=[[0, 100]],
            completed_at=timezone.now(),
        )
        with self.assertRaises(ValidationError):
            services.certify(self.owner, self.enrollment, "Watched the video")
        self.assertEqual(Certification.objects.count(), 0)

    def test_manager_signoff_and_snapshot(self):
        self.complete_evidence()
        with self.assertRaises(PermissionDenied):
            services.certify(self.rep, self.enrollment, "Self-approved")
        cert = services.certify(
            self.owner,
            self.enrollment,
            "Observed accurate discovery, handoff and role boundaries.",
        )
        self.assertEqual(
            cert.requirements_snapshot["modules"][0]["version"], self.version.pk
        )
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.phase, "independent")
        with self.assertRaises(ValidationError):
            services.certify(self.owner, self.enrollment, "Duplicate")

    def test_critical_failure_blocks_high_score(self):
        attempt = self.complete_evidence()
        attempt.critical_failures = ["Ignored DNC"]
        attempt.save()
        with self.assertRaises(ValidationError):
            services.certify(self.owner, self.enrollment, "High score alone")

    def test_empty_or_incomplete_tracks_cannot_certify(self):
        self.complete_evidence()
        Module.objects.create(
            track=self.track,
            title="Unproduced required lesson",
            slug="pending",
            position=2,
        )
        with self.assertRaises(ValidationError):
            services.certify(self.owner, self.enrollment, "Missing lesson")
        empty = Track.objects.create(
            course=self.course, title="Empty", slug="empty", kind="core"
        )
        enrollment = services.enroll(self.owner, self.rep, empty)
        self.assertTrue(services.requirements(enrollment)["gaps"])

    def test_retraining_preserves_old_progress_attempts_and_revokes_award(self):
        self.complete_evidence()
        cert = services.certify(self.owner, self.enrollment, "Initial review")
        previous = EmployeeProgress.objects.get(employee=self.rep, version=self.version)
        services.assign_retraining(
            self.owner, self.enrollment, self.version, "Practice listening again"
        )
        previous.refresh_from_db()
        self.assertEqual(services.watched(previous), 100)
        self.assertEqual(
            EmployeeProgress.objects.filter(
                employee=self.rep, version=self.version
            ).count(),
            2,
        )
        self.assertEqual(QuizAttempt.objects.count(), 1)
        cert.refresh_from_db()
        self.assertIsNotNone(cert.revoked_at)
        self.assertTrue(services.requirements(self.enrollment)["gaps"])
        self.assertFalse(services.module_state(self.rep, self.version)["video"])

    def test_retired_version_preserves_history_and_cannot_earn_more_credit(self):
        self.complete_evidence()
        services.transition(self.owner, self.version, "retired")
        self.version.refresh_from_db()
        self.assertEqual(QuizAttempt.objects.count(), 1)
        with self.assertRaises(PermissionDenied):
            services.submit_quiz(
                self.rep, self.quiz, {str(self.question.pk): 0}, uuid.uuid4()
            )
        self.assertTrue(services.requirements(self.enrollment)["gaps"])

    def test_roleplay_records_are_private_and_retries_link_to_previous(self):
        self.publish()
        response = self.client.post(
            reverse("training_practice_start", args=[self.scenario.pk])
        )
        self.assertEqual(response.status_code, 302)
        attempt = RolePlayAttempt.objects.get()
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(
                reverse("training_practice", args=[attempt.pk])
            ).status_code,
            404,
        )
        self.client.force_login(self.rep)
        data = {"message": "How do you follow up now?", "nonce": str(uuid.uuid4())}
        url = reverse("training_practice_turn", args=[attempt.pk])
        first = self.client.post(
            url, data=json.dumps(data), content_type="application/json"
        )
        second = self.client.post(
            url, data=json.dumps(data), content_type="application/json"
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["transcript"], second.json()["transcript"])
        self.assertTrue(first.json()["guided"])
        self.client.post(
            reverse("training_practice_finish", args=[attempt.pk]),
            {
                "handoff": "FACT: owner described quote follow-up. HYPOTHESIS: explore automation. NEXT: unconfirmed."
            },
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "review")
        self.assertIsNone(attempt.score)
        self.client.post(reverse("training_practice_start", args=[self.scenario.pk]))
        self.assertEqual(
            RolePlayAttempt.objects.exclude(pk=attempt.pk).get().previous_id, attempt.pk
        )

    def test_manager_roleplay_review_creates_skill_evidence(self):
        self.publish()
        attempt = RolePlayAttempt.objects.create(
            employee=self.rep,
            scenario=self.scenario,
            state="review",
            handoff="Fact and next step",
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("training_manager_action", args=[self.enrollment.pk]),
            {
                "action": "roleplay",
                "attempt": attempt.pk,
                "score_listening": "8",
                "critical": "",
                "note": "Followed the actual quote problem; next time ask how follow-up is assigned.",
            },
        )
        self.assertEqual(response.status_code, 302)
        attempt.refresh_from_db()
        self.assertEqual(attempt.score, 8)
        self.assertEqual(EmployeeSkill.objects.get().source, "manager_review")
        self.assertEqual(ManagerReview.objects.get().roleplay_id, attempt.pk)

    def test_guru_context_is_scoped_and_cannot_certify(self):
        self.publish()
        QuizAttempt.objects.create(
            employee=self.other,
            quiz=self.quiz,
            nonce=uuid.uuid4(),
            answers={},
            feedback=[],
            score=13,
            pass_percent=80,
            passed=False,
        )
        data = proctor.context(self.rep, self.version)
        self.assertEqual(data["recent_quizzes"], [])
        text = proctor.prompt(self.rep, self.version, "coach")
        self.assertIn("HUMAN AI Specialist", text)
        self.assertIn("cannot edit CRM", text)
        session = ProctorSession.objects.create(
            employee=self.rep, version=self.version, mode="teach"
        )
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(reverse("training_proctor", args=[session.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("concierge"), {"proctor": str(session.pk)}
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("concierge"), {"proctor": "bad"}).status_code, 404
        )

    @patch("training.proctor.concierge.runway_request")
    def test_runway_proctor_has_scoped_personality_no_action_tools(self, request):
        session = ProctorSession.objects.create(
            employee=self.rep, version=self.version, mode="retest"
        )
        proctor.create_session(session)
        body = request.call_args.args[2]
        self.assertEqual(body["tools"], [])
        self.assertIn("MODE: retest", body["personality"])
        self.assertLessEqual(len(body["personality"]), 10000)

    def test_proctor_keeps_lesson_knowledge_when_history_is_full(self):
        self.version.job_aid = "Ask how quotations are assigned. " * 40
        data = proctor.context(self.rep, self.version)
        data["module_progress"] = [{"lesson": "Older activity " * 30}] * 16
        data["recent_practice"] = [{"feedback": "Previous coaching " * 100}] * 2
        with patch("training.proctor.context", return_value=data):
            text = proctor.prompt(self.rep, self.version, "teach")
        self.assertLessEqual(len(text), 9900)
        payload = json.loads(text.split("SCOPED LEARNING CONTEXT:\n", 1)[1])
        self.assertEqual(payload["lesson"]["field_guide"], self.version.job_aid)
        self.assertIn("ONLY qualified human AI Specialists may discuss pricing", text)

    def test_asset_access_is_private_and_short_lived(self):
        self.publish()
        url = reverse("training_asset", args=[self.version.pk, "video"])
        with patch(
            "training.media.media_url",
            return_value="https://media.example/lesson?short-lived-signature",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("no-store", response["Cache-Control"])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_media_key_validation(self):
        from .media import media_url

        obj = self.version.assets.get(kind="video")
        obj.storage_key = "../secret"
        with self.assertRaises(ValidationError):
            media_url(obj)

    def test_private_disk_playback_still_requires_assigned_employee(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "training/v1/lesson.mp4"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"0123456789")
            with override_settings(TRAINING_S3_BUCKET="", TRAINING_MEDIA_ROOT=folder):
                self.publish()
                url = reverse("training_asset", args=[self.version.pk, "video"])
                response = self.client.get(url, HTTP_RANGE="bytes=2-4")
                self.assertEqual(response.status_code, 206)
                self.assertEqual(b"".join(response.streaming_content), b"234")
                response.close()
                self.client.force_login(self.other)
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_seed_is_idempotent_and_never_publishes_or_creates_crm_leads(self):
        from crm.models import Lead

        before = Lead.objects.count()
        call_command("seed_training", verbosity=0)
        count = ModuleVersion.objects.count()
        call_command("seed_training", verbosity=0)
        self.assertEqual(ModuleVersion.objects.count(), count)
        self.assertEqual(Lead.objects.count(), before)
        version = ModuleVersion.objects.get(module__slug="core-sdr-01")
        self.assertEqual(version.status, "owner_review")
        self.assertEqual(version.quiz.questions.count(), 8)
        self.assertEqual(version.module.track.modules.count(), 16)
        self.assertEqual(version.scenes[-1]["end"], 900)
        self.assertGreater(len(version.transcript.split()), 1800)

    def test_pricing_amendment_creates_revision_without_erasing_evidence(self):
        call_command("seed_training", verbosity=0)
        original = ModuleVersion.objects.get(module__slug="core-sdr-01")
        original.policy_version = "2026-09-25"
        original.transcript = "Historical policy allows starting prices."
        original.save()
        progress = EmployeeProgress.objects.create(
            employee=self.rep, version=original, watched_ranges=[[0, 20]]
        )
        old_quiz_id = original.quiz.pk
        call_command("seed_training", verbosity=0)
        revised = original.module.versions.order_by("-number").first()
        original.refresh_from_db()
        progress.refresh_from_db()
        self.assertEqual(
            original.transcript, "Historical policy allows starting prices."
        )
        self.assertEqual(progress.version_id, original.pk)
        self.assertEqual(original.quiz.pk, old_quiz_id)
        self.assertEqual(revised.policy_version, "2026-09-27")
        self.assertEqual(revised.status, "owner_review")
        self.assertIn("only during a Growth Assessment", revised.transcript)
        self.assertNotIn("$997", revised.job_aid)
        self.assertNotIn("twenty-five hundred", revised.transcript)
        self.assertNotEqual(revised.quiz.pk, old_quiz_id)
        call_command("seed_training", verbosity=0)
        self.assertEqual(original.module.versions.count(), 2)

    def test_proctor_teaches_specialist_only_pricing_during_assessment(self):
        instructions = proctor.prompt(self.rep, self.version, "coach")
        self.assertIn(
            "ONLY qualified human AI Specialists may discuss pricing", instructions
        )
        self.assertIn("ONLY during a Growth Assessment", instructions)
        self.assertIn("SDRs and Guru must not give starting prices", instructions)
        self.assertNotIn("$2,500", instructions)

    def test_stale_content_instances_cannot_mutate_or_credit_after_publication(self):
        question = Question.objects.select_related("quiz__version").get(
            pk=self.question.pk
        )
        quiz = Quiz.objects.select_related("version").get(pk=self.quiz.pk)
        self.publish()
        question.prompt = "Mutated via cached relation"
        with self.assertRaises(ValidationError):
            question.save()
        with self.assertRaises(ValidationError):
            Question.objects.create(
                quiz=quiz,
                prompt="Extra",
                choices=["A", "B"],
                correct_index=0,
                explanation="A",
            )
        services.transition(self.owner, self.version, "retired")
        with self.assertRaises(PermissionDenied):
            services.heartbeat(
                self.rep, self.version, {"position": 0, "session": str(uuid.uuid4())}
            )

    def test_revision_copies_content_without_approval_or_employee_evidence(self):
        self.publish()
        new = services.clone_version(self.owner, self.version)
        self.assertEqual(new.number, 2)
        self.assertEqual(new.status, "draft")
        self.assertEqual(new.quiz.questions.get().prompt, self.question.prompt)
        self.assertFalse(new.assets.filter(reviewed=True).exists())
        self.assertFalse(EmployeeProgress.objects.filter(version=new).exists())
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, "published")
        with self.assertRaises(PermissionDenied):
            services.clone_version(self.rep, self.version)

    def test_manager_score_form_uses_named_skill_controls(self):
        RolePlayAttempt.objects.create(
            employee=self.rep, scenario=self.scenario, state="review"
        )
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("training_employee", args=[self.enrollment.pk])
        )
        self.assertContains(response, 'name="score_listening"')
        self.assertNotContains(response, "Skill scores (JSON")
        self.assertEqual(
            self.client.post(
                reverse("training_assign"), {"employee": "bad", "track": "bad"}
            ).status_code,
            404,
        )

    def test_history_preserves_retired_attempts_and_is_private(self):
        self.publish()
        services.submit_quiz(
            self.rep, self.quiz, {str(self.question.pk): 0}, uuid.uuid4()
        )
        services.transition(self.owner, self.version, "retired")
        response = self.client.get(reverse("training_history"))
        self.assertContains(response, "Respect contact restrictions.")
        self.client.force_login(self.other)
        self.assertNotContains(
            self.client.get(reverse("training_history")),
            "Respect contact restrictions.",
        )

    @override_settings(PLATFORM_OPENAI_API_KEY="test-only-not-a-real-key")
    @patch("training.proctor.PlatformAIService.structured_json")
    def test_guru_advisory_evidence_does_not_certify(self, mocked):
        attempt = RolePlayAttempt.objects.create(
            employee=self.rep,
            scenario=self.scenario,
            state="review",
            transcript=[{"role": "user", "content": "How do quotes get followed up?"}],
            handoff="FACT: quote follow-up is inconsistent.",
        )
        mocked.return_value = (
            {
                "skills": [
                    {
                        "skill": "listening",
                        "score": 8,
                        "quote": "How do quotes get followed up?",
                        "feedback": "You followed the named problem.",
                    }
                ],
                "retry": "Ask who owns the follow-up next.",
            },
            {"status": "success"},
        )
        proctor.assess(attempt)
        proctor.assess(attempt)
        attempt.refresh_from_db()
        self.assertEqual(attempt.state, "review")
        self.assertIsNone(attempt.score)
        self.assertEqual(attempt.advisory_feedback["skills"][0]["score"], 8)
        self.assertEqual(
            EmployeeSkill.objects.filter(source="guru_advisory").count(), 1
        )
        self.assertFalse(Certification.objects.exists())

    @override_settings(PLATFORM_OPENAI_API_KEY="test-only-not-a-real-key")
    @patch("training.proctor.PlatformAIService.structured_json")
    def test_guru_rejects_fabricated_evidence(self, mocked):
        attempt = RolePlayAttempt.objects.create(
            employee=self.rep,
            scenario=self.scenario,
            state="review",
            transcript=[{"role": "user", "content": "Hello"}],
        )
        mocked.return_value = (
            {
                "skills": [
                    {
                        "skill": "listening",
                        "score": 10,
                        "quote": "Imaginary perfect question",
                        "feedback": "Excellent.",
                    }
                ],
                "retry": "Continue.",
            },
            {"status": "success"},
        )
        proctor.assess(attempt)
        attempt.refresh_from_db()
        self.assertEqual(attempt.advisory_feedback, {})
        self.assertFalse(EmployeeSkill.objects.exists())

    def test_raising_watch_threshold_requires_more_coverage(self):
        self.publish()
        EmployeeProgress.objects.create(
            employee=self.rep,
            version=self.version,
            watched_ranges=[[0, 90]],
            completed_at=timezone.now(),
        )
        self.assertTrue(services.module_state(self.rep, self.version)["video"])
        self.version.module.track.watch_percent = 100
        self.version.module.track.save()
        self.assertFalse(services.module_state(self.rep, self.version)["video"])

    @patch("assistant_ai.concierge.is_available", return_value=True)
    @patch("training.proctor.create_session")
    def test_proctor_start_rechecks_ownership_and_excludes_visitor_memory(
        self, create_session, available
    ):
        session = ProctorSession.objects.create(
            employee=self.rep, version=self.version, mode="coach"
        )
        create_session.return_value = {"id": str(uuid.uuid4())}
        url = reverse("concierge_start")
        body = {"consent": True, "proctor": str(session.pk)}
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.post(
                url, data=json.dumps(body), content_type="application/json"
            ).status_code,
            404,
        )
        self.client.force_login(self.rep)
        self.assertEqual(
            self.client.post(
                url,
                data=json.dumps({**body, "salesGuide": True}),
                content_type="application/json",
            ).status_code,
            400,
        )
        response = self.client.post(
            url, data=json.dumps(body), content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["contextUrl"])
        self.assertNotIn("concierge_guru_call", self.client.session)
        create_session.assert_called_once()
