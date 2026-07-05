from django.apps import apps
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .threadlocal import get_current_request, get_current_user
from .utils import log_activity

WATCHED_MODELS = {
    "accounts.User",
    "clients.ClientAccount",
    "clients.BusinessProfile",
    "clients.Integration",
    "clients.AIInstance",
    "crm.Lead",
    "crm.LeadNote",
    "assistant_ai.Conversation",
    "assistant_ai.Message",
    "assistant_ai.KnowledgeDocument",
    "voice.CallLog",
    "voice.SMSLog",
    "billing.BillingCustomer",
    "core.ConsultationRequest",
    "core.IndustryTemplate",
}

def model_label(instance):
    return f"{instance._meta.app_label}.{instance.__class__.__name__}"

def should_watch(instance):
    return model_label(instance) in WATCHED_MODELS

@receiver(post_save)
def audit_model_save(sender, instance, created, **kwargs):
    if not should_watch(instance):
        return
    user = get_current_user()
    request = get_current_request()
    if user is None and request is None:
        return
    action = "create" if created else "update"
    log_activity(
        user=user,
        request=request,
        action=action,
        model_label=model_label(instance),
        object_id=getattr(instance, "pk", ""),
        object_repr=str(instance),
        message=f"{action.title()} {model_label(instance)}",
        metadata={"created": created},
    )

@receiver(post_delete)
def audit_model_delete(sender, instance, **kwargs):
    if not should_watch(instance):
        return
    user = get_current_user()
    request = get_current_request()
    if user is None and request is None:
        return
    log_activity(
        user=user,
        request=request,
        action="delete",
        model_label=model_label(instance),
        object_id=getattr(instance, "pk", ""),
        object_repr=str(instance),
        message=f"Deleted {model_label(instance)}",
    )
