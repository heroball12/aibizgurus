from datetime import timedelta
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import get_valid_filename


def staff_message_attachment_path(instance, filename):
    safe_name = get_valid_filename(Path(filename).name or "attachment")
    unique = uuid.uuid4().hex[:12]
    return f"staff_messages/thread_{instance.message.thread_id}/message_{instance.message_id}/{unique}_{safe_name}"

class ActivityLog(models.Model):
    ACTION_CHOICES = [
        ("request", "Page / Request"),
        ("create", "Create"),
        ("update", "Update"),
        ("delete", "Delete"),
        ("login", "Login"),
        ("logout", "Logout"),
        ("billing", "Billing"),
        ("integration", "Integration"),
        ("assistant", "Assistant"),
        ("other", "Other"),
    ]

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_logs")
    actor_username = models.CharField(max_length=150, blank=True)
    actor_role = models.CharField(max_length=50, blank=True)
    action = models.CharField(max_length=40, choices=ACTION_CHOICES, default="other")

    path = models.CharField(max_length=500, blank=True)
    method = models.CharField(max_length=20, blank=True)
    status_code = models.PositiveIntegerField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    model_label = models.CharField(max_length=120, blank=True)
    object_id = models.CharField(max_length=120, blank=True)
    object_repr = models.CharField(max_length=300, blank=True)

    message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["actor", "created_at"]),
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["model_label", "object_id"]),
        ]

    def __str__(self):
        who = self.actor_username or "System"
        target = self.object_repr or self.path or self.model_label or "activity"
        return f"{who} {self.action} {target}"


class StaffMessageThread(models.Model):
    title = models.CharField(max_length=180, blank=True)
    is_group = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_staff_message_threads",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["updated_at"]),
            models.Index(fields=["created_by", "updated_at"]),
            models.Index(fields=["is_group", "updated_at"]),
        ]

    def __str__(self):
        return self.title or f"Staff thread #{self.pk}"

    def participant_names(self):
        names = []
        for participant in self.participants.select_related("user").all():
            user = participant.user
            names.append(user.get_full_name() or user.username)
        return ", ".join(names)

    def display_title(self):
        return self.title or self.participant_names() or str(self)


class StaffMessageParticipant(models.Model):
    thread = models.ForeignKey(StaffMessageThread, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_message_participations")
    joined_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("thread", "user")]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["thread", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user} in {self.thread}"


class StaffMessage(models.Model):
    thread = models.ForeignKey(StaffMessageThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_staff_messages")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["thread", "created_at"]),
            models.Index(fields=["sender", "created_at"]),
        ]

    def __str__(self):
        return f"{self.sender or 'System'} · {self.created_at:%Y-%m-%d %H:%M}"


class StaffMessageAttachment(models.Model):
    message = models.ForeignKey(StaffMessage, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=staff_message_attachment_path)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_staff_message_attachments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["message", "created_at"]),
            models.Index(fields=["uploaded_by", "created_at"]),
        ]

    @property
    def size_label(self):
        if self.size >= 1024 * 1024:
            return f"{self.size / (1024 * 1024):.1f} MB"
        if self.size >= 1024:
            return f"{self.size / 1024:.1f} KB"
        return f"{self.size} B"

    def __str__(self):
        return self.original_filename


class TimeClockEntry(models.Model):
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="time_clock_entries")
    clock_in = models.DateTimeField(default=timezone.now)
    clock_out = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    clock_in_ip = models.GenericIPAddressField(null=True, blank=True)
    clock_out_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-clock_in"]
        indexes = [
            models.Index(fields=["employee", "clock_in"]),
            models.Index(fields=["employee", "clock_out"]),
            models.Index(fields=["clock_out", "clock_in"]),
        ]

    @property
    def is_open(self):
        return self.clock_out is None

    @property
    def duration(self):
        end = self.clock_out or timezone.now()
        return max(end - self.clock_in, timedelta())

    @property
    def duration_hours(self):
        return round(self.duration.total_seconds() / 3600, 2)

    def __str__(self):
        return f"{self.employee} · {self.clock_in:%Y-%m-%d %H:%M}"
