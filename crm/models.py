from django.conf import settings
from django.db import models

class Lead(models.Model):
    LEAD_TYPE_CHOICES = [("internal_sales","Internal Sales Lead"),("client_customer","Client Customer Lead")]
    STATUS_CHOICES = [("new","New"),("contacted","Contacted"),("demo_sent","Demo Sent"),("follow_up","Follow-Up Needed"),("closed_won","Closed Won"),("closed_lost","Closed Lost"),("client_onboarded","Client Onboarded")]
    client = models.ForeignKey("clients.ClientAccount", on_delete=models.CASCADE, null=True, blank=True, related_name="leads")
    ai_instance = models.ForeignKey("clients.AIInstance", on_delete=models.SET_NULL, null=True, blank=True, related_name="leads")
    lead_type = models.CharField(max_length=30, choices=LEAD_TYPE_CHOICES, default="internal_sales")
    name = models.CharField(max_length=150, blank=True)
    business_name = models.CharField(max_length=200, blank=True)
    industry = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=80, blank=True)
    email = models.EmailField(blank=True)
    source = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="new")
    notes = models.TextField(blank=True)
    value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name or self.business_name or f"Lead {self.pk}"

class LeadNote(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="lead_notes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
