from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Lead
from core.alerts import notify_lead_created

@receiver(post_save, sender=Lead)
def lead_created_alert(sender, instance, created, **kwargs):
    if created:
        notify_lead_created(instance)
