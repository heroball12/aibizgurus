from django.db import models

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

    def __str__(self):
        return f"{self.ai_instance.name} conversation {self.pk}"

class Message(models.Model):
    SENDER_CHOICES = [("visitor","Visitor"),("assistant","Assistant"),("system","System"),("staff","Staff")]
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=30, choices=SENDER_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

class KnowledgeDocument(models.Model):
    ai_instance = models.ForeignKey("clients.AIInstance", on_delete=models.CASCADE, related_name="knowledge_documents")
    title = models.CharField(max_length=200)
    content = models.TextField()
    processed_status = models.CharField(max_length=50, default="ready")
    created_at = models.DateTimeField(auto_now_add=True)
