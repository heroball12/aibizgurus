from django.db import models
from django.utils.text import slugify

class IndustryTemplate(models.Model):
    name = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=190, unique=True, blank=True)
    category = models.CharField(max_length=100, blank=True)
    is_supported = models.BooleanField(default=True)
    summary = models.TextField(blank=True)
    default_greeting = models.TextField(blank=True)
    system_prompt = models.TextField(blank=True)
    lead_fields = models.JSONField(default=list, blank=True)
    common_questions = models.JSONField(default=list, blank=True)
    escalation_rules = models.TextField(blank=True)

    class Meta:
        ordering = ["category", "name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class ConsultationRequest(models.Model):
    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=80, blank=True)
    business_name = models.CharField(max_length=200, blank=True)
    industry = models.CharField(max_length=150)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=50, default="new")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.industry} - {self.name}"
