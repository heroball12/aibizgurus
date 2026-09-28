"""Versioned learning content and private, append-only assessment evidence."""

import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class Course(models.Model):
    title = models.CharField(max_length=160)
    slug = models.SlugField(unique=True)

    def __str__(self):
        return self.title


class Track(models.Model):
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="tracks")
    title = models.CharField(max_length=160)
    slug = models.SlugField(unique=True)
    kind = models.CharField(
        max_length=20,
        choices=[
            ("core", "Core SDR"),
            ("advanced", "Advanced sales"),
            ("industry", "Industry specialization"),
        ],
    )
    description = models.TextField(blank=True)
    quiz_pass_percent = models.PositiveSmallIntegerField(
        default=80, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    roleplay_pass_score = models.PositiveSmallIntegerField(
        default=8, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    watch_percent = models.PositiveSmallIntegerField(
        default=90, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    thresholds_proposed = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title


class Skill(models.Model):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=100)

    def __str__(self):
        return self.title


class Module(models.Model):
    track = models.ForeignKey(Track, on_delete=models.PROTECT, related_name="modules")
    title = models.CharField(max_length=180)
    slug = models.SlugField(unique=True)
    position = models.PositiveSmallIntegerField()
    required = models.BooleanField(default=True)
    skills = models.ManyToManyField(Skill, blank=True)

    class Meta:
        ordering = ["track_id", "position"]

    def __str__(self):
        return self.title


class ModuleVersion(models.Model):
    STATES = [
        ("draft", "Draft"),
        ("owner_review", "Owner review"),
        ("approved", "Approved"),
        ("published", "Published"),
        ("retired", "Retired"),
    ]
    module = models.ForeignKey(
        Module, on_delete=models.PROTECT, related_name="versions"
    )
    number = models.PositiveIntegerField(default=1)
    policy_version = models.CharField(max_length=50, default="2026-09-25")
    status = models.CharField(max_length=20, choices=STATES, default="draft")
    summary = models.TextField(blank=True)
    transcript = models.TextField(blank=True)
    scenes = models.JSONField(default=list, blank=True)
    job_aid = models.TextField(blank=True)
    duration_seconds = models.PositiveIntegerField(
        default=900, validators=[MinValueValidator(1)]
    )
    published_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["module", "number"], name="training_module_version"
            )
        ]

    def __str__(self):
        return f"{self.module} · v{self.number}"

    @property
    def runtime_label(self):
        minutes, seconds = divmod(self.duration_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            content_fields = [
                "module_id",
                "number",
                "policy_version",
                "summary",
                "transcript",
                "scenes",
                "job_aid",
                "duration_seconds",
            ]
            if previous.status in {"approved", "published", "retired"} and any(
                getattr(previous, k) != getattr(self, k) for k in content_fields
            ):
                raise ValidationError(
                    "Approved content is immutable. Create a new version."
                )
            state_fields = [
                "status",
                "published_at",
                "retired_at",
                "approved_by_id",
                "approved_at",
            ]
            if any(
                getattr(previous, k) != getattr(self, k) for k in state_fields
            ) and not getattr(self, "_transition", False):
                raise ValidationError("Use the owner publication workflow.")
        elif self.status != "draft":
            raise ValidationError("New versions start in draft.")
        super().save(*args, **kwargs)
        self._transition = False


class VersionedContent(models.Model):
    class Meta:
        abstract = True

    def version_record(self):
        return ModuleVersion.objects.get(pk=self.version_id)

    def save(self, *args, **kwargs):
        if self.version_record().status in {"approved", "published", "retired"}:
            raise ValidationError(
                "Create a new module version to change approved content."
            )
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            if previous.version_record().status in {"approved", "published", "retired"}:
                raise ValidationError(
                    "Approved content cannot be moved to another version."
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.version_record().status in {"approved", "published", "retired"}:
            raise ValidationError("Approved content cannot be deleted.")
        super().delete(*args, **kwargs)


class LessonAsset(VersionedContent):
    version = models.ForeignKey(
        ModuleVersion, on_delete=models.PROTECT, related_name="assets"
    )
    kind = models.CharField(
        max_length=20,
        choices=[("video", "Video"), ("captions", "Captions"), ("poster", "Poster")],
    )
    storage_key = models.CharField(max_length=500)
    reviewed = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["version", "kind"], name="training_asset_kind"
            )
        ]


class Quiz(VersionedContent):
    version = models.OneToOneField(
        ModuleVersion, on_delete=models.PROTECT, related_name="quiz"
    )
    title = models.CharField(max_length=180, default="Apply what you learned")


class Question(VersionedContent):
    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT, related_name="questions")
    prompt = models.TextField()
    choices = models.JSONField(default=list)
    correct_index = models.PositiveSmallIntegerField()
    explanation = models.TextField()
    position = models.PositiveSmallIntegerField(default=1)
    skill = models.ForeignKey(Skill, on_delete=models.PROTECT, null=True, blank=True)

    def version_record(self):
        return ModuleVersion.objects.get(quiz__pk=self.quiz_id)

    def clean(self):
        if (
            not isinstance(self.choices, list)
            or not 2 <= len(self.choices) <= 6
            or not all(isinstance(c, str) for c in self.choices)
        ):
            raise ValidationError("Provide 2–6 text choices.")
        if self.correct_index >= len(self.choices):
            raise ValidationError("Choose an available answer.")

    class Meta:
        ordering = ["position", "pk"]


class CertificationAttempt(models.Model):
    PHASES = [
        ("training", "Training"),
        ("shadowing", "Shadowing"),
        ("supervised", "Supervised calling"),
        ("independent", "Certified / independent"),
    ]
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="training_enrollments",
    )
    track = models.ForeignKey(Track, on_delete=models.PROTECT)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    phase = models.CharField(max_length=20, choices=PHASES, default="training")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "track"], name="training_enrollment"
            )
        ]


class TrainingAssignment(models.Model):
    enrollment = models.ForeignKey(
        CertificationAttempt, on_delete=models.PROTECT, related_name="assignments"
    )
    version = models.ForeignKey(ModuleVersion, on_delete=models.PROTECT)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    note = models.TextField(blank=True)
    due_at = models.DateField(null=True, blank=True)
    retraining = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class EmployeeProgress(models.Model):
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    version = models.ForeignKey(ModuleVersion, on_delete=models.PROTECT)
    cycle = models.PositiveIntegerField(default=1)
    watched_ranges = models.JSONField(default=list)
    position_seconds = models.FloatField(default=0)
    active_seconds = models.FloatField(default=0)
    last_ping = models.DateTimeField(null=True, blank=True)
    watch_session = models.UUIDField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "version", "cycle"], name="training_progress"
            )
        ]


class QuizAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT)
    nonce = models.UUIDField()
    answers = models.JSONField()
    feedback = models.JSONField()
    score = models.FloatField()
    pass_percent = models.PositiveSmallIntegerField()
    passed = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "nonce"], name="training_quiz_nonce"
            )
        ]


class RolePlayScenario(VersionedContent):
    version = models.ForeignKey(
        ModuleVersion, on_delete=models.PROTECT, related_name="scenarios"
    )
    title = models.CharField(max_length=160)
    persona = models.TextField()
    opening = models.TextField()
    rubric = models.JSONField(default=dict)
    difficulty = models.PositiveSmallIntegerField(
        default=2, validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    required = models.BooleanField(default=True)
    capstone = models.BooleanField(default=False)


class RolePlayAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    scenario = models.ForeignKey(RolePlayScenario, on_delete=models.PROTECT)
    previous = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True
    )
    transcript = models.JSONField(default=list)
    handoff = models.TextField(blank=True)
    feedback = models.JSONField(default=dict)
    advisory_feedback = models.JSONField(default=dict, blank=True)
    score = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    critical_failures = models.JSONField(default=list)
    state = models.CharField(
        max_length=20,
        choices=[
            ("active", "Active"),
            ("review", "Manager review"),
            ("reviewed", "Reviewed"),
        ],
        default="active",
    )
    busy = models.BooleanField(default=False)
    processing_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class EmployeeSkill(models.Model):
    """Evidence per attempt; never a permanent label or opaque employee score."""

    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    skill = models.ForeignKey(Skill, on_delete=models.PROTECT)
    attempt = models.ForeignKey(RolePlayAttempt, on_delete=models.PROTECT)
    score = models.FloatField(validators=[MinValueValidator(1), MaxValueValidator(10)])
    evidence = models.TextField()
    source = models.CharField(max_length=20, default="guru_advisory")
    created_at = models.DateTimeField(auto_now_add=True)


class ManagerReview(models.Model):
    enrollment = models.ForeignKey(
        CertificationAttempt, on_delete=models.PROTECT, related_name="reviews"
    )
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    roleplay = models.ForeignKey(
        RolePlayAttempt, on_delete=models.PROTECT, null=True, blank=True
    )
    kind = models.CharField(
        max_length=30,
        choices=[
            ("roleplay", "Role-play review"),
            ("practical", "Practical evaluation"),
            ("certify", "Certification approval"),
            ("revoke", "Certification revoked"),
        ],
    )
    passed = models.BooleanField(default=False)
    crm_practical = models.BooleanField(default=False)
    note = models.TextField()
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class Certification(models.Model):
    enrollment = models.ForeignKey(
        CertificationAttempt, on_delete=models.PROTECT, related_name="certifications"
    )
    review = models.OneToOneField(ManagerReview, on_delete=models.PROTECT)
    requirements_snapshot = models.JSONField()
    awarded_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class ProctorSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    version = models.ForeignKey(
        ModuleVersion, on_delete=models.PROTECT, null=True, blank=True
    )
    mode = models.CharField(max_length=20, default="coach")
    messages = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
