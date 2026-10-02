"""Experience Center records are intentionally separate from clients and CRM leads."""
import uuid
from django.conf import settings
from django.db import models


class DemoExperience(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=120)
    profile_slug = models.SlugField(default="automotive")
    published = models.BooleanField(default=False)
    public_access = models.BooleanField(default=True)
    current_revision = models.ForeignKey("DemoRevision", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    def __str__(self):
        return self.name


class DemoRevision(models.Model):
    experience = models.ForeignKey(DemoExperience, on_delete=models.CASCADE, related_name="revisions")
    version = models.CharField(max_length=64)
    content = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["experience", "version"], name="unique_demo_revision")]

    def __str__(self):
        return f"{self.experience} · {self.version}"


class DemoRepAccess(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="demo_access")
    enabled = models.BooleanField(default=True)


class DemoSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    revision = models.ForeignKey(DemoRevision, on_delete=models.PROTECT)
    browser_key = models.CharField(max_length=64, db_index=True)
    rep = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="experience_sessions")
    source = models.CharField(max_length=30, default="public")
    scenario = models.SlugField(default="vehicle-shopping")
    state = models.JSONField(default=dict)
    transcript = models.JSONField(default=list)
    protocol = models.JSONField(default=list)
    turns = models.PositiveIntegerField(default=0)
    lease = models.UUIDField(null=True, blank=True)
    busy_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True)


class DemoEvent(models.Model):
    session = models.ForeignKey(DemoSession, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=60, db_index=True)
    metadata = models.JSONField(default=dict)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class DemoShareLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    experience = models.ForeignKey(DemoExperience, on_delete=models.CASCADE)
    rep = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    scenario = models.SlugField(default="vehicle-shopping")
    created_at = models.DateTimeField(auto_now_add=True)


class DemoConversion(models.Model):
    """Only a deliberately submitted real assessment request reaches this table."""
    consultation = models.OneToOneField("ConsultationRequest", on_delete=models.CASCADE)
    session = models.ForeignKey(DemoSession, null=True, blank=True, on_delete=models.SET_NULL)
    rep = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    vertical = models.SlugField()
    scenario = models.SlugField()
    source = models.CharField(max_length=30)
    revision = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)


class DemoFeedback(models.Model):
    CATEGORIES = [(k, v) for k, v in [
        ("answer", "AI answer wrong"), ("inventory", "Inventory mismatch"),
        ("voice", "Voice problem"), ("ui", "UI problem"), ("slow", "Too slow"),
        ("scenario", "Scenario problem"), ("question", "Prospect question"),
        ("feature", "Feature request"), ("other", "Other")]]
    session = models.ForeignKey(DemoSession, null=True, on_delete=models.SET_NULL)
    rep = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    category = models.CharField(max_length=20, choices=CATEGORIES)
    notes = models.TextField(max_length=2000)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class DemoCRMLead(models.Model):
    """A fictional dealership's customer record, scoped to exactly one demo session."""
    session = models.OneToOneField(DemoSession, on_delete=models.CASCADE, related_name="dealership_lead")
    customer_name = models.CharField(max_length=100, default="Demo Customer")
    stage = models.CharField(max_length=30, default="new")
    assigned_to = models.CharField(max_length=100, default="Elena Rivera · BDC")
    snapshot = models.JSONField(default=dict)
    staff_notes = models.TextField(blank=True, max_length=3000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class DemoCRMActivity(models.Model):
    lead = models.ForeignKey(DemoCRMLead, on_delete=models.CASCADE, related_name="activity")
    action = models.CharField(max_length=100)
    description = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
