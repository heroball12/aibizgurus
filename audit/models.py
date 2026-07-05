from django.conf import settings
from django.db import models

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
