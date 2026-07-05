from django.db import models

class CallLog(models.Model):
    ai_instance = models.ForeignKey("clients.AIInstance", on_delete=models.CASCADE, related_name="call_logs")
    from_number = models.CharField(max_length=80, blank=True)
    to_number = models.CharField(max_length=80, blank=True)
    call_sid = models.CharField(max_length=120, blank=True)
    transcript = models.TextField(blank=True)
    summary = models.TextField(blank=True)
    status = models.CharField(max_length=60, default="received")
    created_at = models.DateTimeField(auto_now_add=True)

class SMSLog(models.Model):
    ai_instance = models.ForeignKey("clients.AIInstance", on_delete=models.CASCADE, related_name="sms_logs")
    from_number = models.CharField(max_length=80, blank=True)
    to_number = models.CharField(max_length=80, blank=True)
    body = models.TextField(blank=True)
    response = models.TextField(blank=True)
    message_sid = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
