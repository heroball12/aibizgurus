import uuid
import time
from django.core.cache import cache
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_exempt
from clients.models import AIInstance
from .models import Conversation, Message
from .services import generate_ai_reply
from crm.models import Lead


def _can_use_widget(request, instance):
    if instance.client.is_paid_active and instance.status == "active" and instance.embed_enabled:
        return True
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return False
    return user.is_employee_or_admin() or instance.client.user_id == user.pk

def _rate_limited(request, slug, limit=40, window=60):
    ip = request.META.get("REMOTE_ADDR", "unknown")
    key = f"widget_rate:{slug}:{ip}"
    data = cache.get(key, {"count": 0, "reset": time.time() + window})
    now = time.time()
    if now > data["reset"]:
        data = {"count": 0, "reset": now + window}
    data["count"] += 1
    cache.set(key, data, timeout=window)
    return data["count"] > limit


@xframe_options_exempt
def widget(request, slug):
    instance = get_object_or_404(AIInstance, slug=slug)
    if not _can_use_widget(request, instance):
        raise Http404("Widget disabled")
    return render(request, "assistant_ai/widget.html", {"instance": instance})

@csrf_exempt
def widget_chat_api(request, slug):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    if _rate_limited(request, slug):
        return JsonResponse({"error": "Rate limit exceeded. Please wait a moment."}, status=429)
    instance = get_object_or_404(AIInstance, slug=slug)
    if not _can_use_widget(request, instance):
        raise Http404("Widget unavailable")
    visitor_id = request.POST.get("visitor_id") or str(uuid.uuid4())
    message = request.POST.get("message", "").strip()
    if not message:
        return JsonResponse({"error": "Empty message"}, status=400)

    conversation_id = request.POST.get("conversation_id")
    conversation = Conversation.objects.filter(pk=conversation_id, ai_instance=instance).first() if conversation_id else None
    if not conversation:
        conversation = Conversation.objects.create(
            ai_instance=instance,
            visitor_id=visitor_id,
            customer_name=request.POST.get("name", ""),
            customer_phone=request.POST.get("phone", ""),
            customer_email=request.POST.get("email", ""),
            channel="web",
        )
    else:
        changed_fields = []
        for field, post_key in [
            ("customer_name", "name"),
            ("customer_phone", "phone"),
            ("customer_email", "email"),
        ]:
            value = request.POST.get(post_key, "").strip()
            if value and not getattr(conversation, field):
                setattr(conversation, field, value)
                changed_fields.append(field)
        if changed_fields:
            conversation.save(update_fields=changed_fields + ["updated_at"])

    Message.objects.create(conversation=conversation, sender="visitor", content=message)
    reply = generate_ai_reply(instance, conversation, message)
    Message.objects.create(conversation=conversation, sender="assistant", content=reply)
    conversation.save(update_fields=["updated_at"])

    if any(x in message.lower() for x in ["quote", "book", "appointment", "order", "urgent", "asap", "pricing", "call me"]):
        Lead.objects.create(
            client=instance.client,
            ai_instance=instance,
            lead_type="client_customer",
            name=request.POST.get("name", "") or "Website visitor",
            phone=request.POST.get("phone", ""),
            email=request.POST.get("email", ""),
            source="AI widget",
            status="new",
            notes=f"Visitor: {message}\nAssistant: {reply}",
        )

    return JsonResponse({"reply": reply, "visitor_id": visitor_id, "conversation_id": conversation.pk})
