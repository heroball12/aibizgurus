from django.db import models

class BillingCustomer(models.Model):
    client = models.OneToOneField("clients.ClientAccount", on_delete=models.CASCADE, related_name="billing_customer")
    stripe_customer_id = models.CharField(max_length=150, blank=True)
    stripe_subscription_id = models.CharField(max_length=150, blank=True)
    plan = models.CharField(max_length=100, default="starter")
    status = models.CharField(max_length=100, default="inactive")
    current_period_end = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
