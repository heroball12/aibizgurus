from django.db import models


class AssistantRole(models.Model):
    ROLE_CHOICES = [
        ("client_assistant", "Client-Facing Assistant"),
        ("sdr_assistant", "SDR Assistant"),
        ("manager_sales", "Manager Sales Assistant"),
        ("growth_assessment", "Growth Assessment Assistant"),
        ("internal_knowledge", "Internal Knowledge Assistant"),
    ]
    key = models.CharField(max_length=80, choices=ROLE_CHOICES, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.name


class AssistantConfiguration(models.Model):
    role = models.ForeignKey(AssistantRole, on_delete=models.CASCADE, related_name="configurations")
    version = models.PositiveIntegerField(default=1)
    system_instructions = models.TextField()
    allowed_tools = models.JSONField(default=list, blank=True)
    model = models.CharField(max_length=100, default="gpt-4o-mini")
    temperature = models.DecimalField(max_digits=3, decimal_places=2, default=0.35)
    max_output_tokens = models.PositiveIntegerField(default=700)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["role__key", "-version"]
        unique_together = [("role", "version")]

    def __str__(self):
        return f"{self.role} v{self.version}"


class UsageRecord(models.Model):
    STATUS_CHOICES = [
        ("success", "Success"),
        ("fallback", "Fallback"),
        ("error", "Error"),
        ("blocked", "Blocked"),
    ]
    user = models.ForeignKey("accounts.User", on_delete=models.SET_NULL, null=True, blank=True)
    client = models.ForeignKey("clients.ClientAccount", on_delete=models.SET_NULL, null=True, blank=True)
    ai_instance = models.ForeignKey("clients.AIInstance", on_delete=models.SET_NULL, null=True, blank=True)
    assistant_role = models.CharField(max_length=80, blank=True)
    model = models.CharField(max_length=100, blank=True)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="success")
    error_code = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["assistant_role", "created_at"]),
            models.Index(fields=["client", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]


class Conversation(models.Model):
    ai_instance = models.ForeignKey("clients.AIInstance", on_delete=models.CASCADE, related_name="conversations")
    visitor_id = models.CharField(max_length=120, blank=True)
    customer_name = models.CharField(max_length=150, blank=True)
    customer_phone = models.CharField(max_length=80, blank=True)
    customer_email = models.EmailField(blank=True)
    summary = models.TextField(blank=True)
    channel = models.CharField(max_length=30, default="web")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["ai_instance", "updated_at"]),
            models.Index(fields=["channel", "updated_at"]),
            models.Index(fields=["customer_email"]),
        ]

    def __str__(self):
        return f"{self.ai_instance.name} conversation {self.pk}"

class Message(models.Model):
    SENDER_CHOICES = [("visitor","Visitor"),("assistant","Assistant"),("system","System"),("staff","Staff")]
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=30, choices=SENDER_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["sender", "created_at"]),
        ]

class KnowledgeDocument(models.Model):
    ai_instance = models.ForeignKey("clients.AIInstance", on_delete=models.CASCADE, related_name="knowledge_documents")
    title = models.CharField(max_length=200)
    content = models.TextField()
    processed_status = models.CharField(max_length=50, default="ready")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["ai_instance", "processed_status"]),
        ]
