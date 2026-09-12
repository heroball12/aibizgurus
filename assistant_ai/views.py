import uuid

from django import forms
from django.core import signing
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_POST

from clients.models import AIInstance
from core.rate_limits import consume_budget, request_identity
from .models import Conversation, Message
from .services import generate_ai_reply, capture_conversation_lead

TOKEN_SALT = "assistant-conversation-v1"


class ChatForm(forms.Form):
    message = forms.CharField(max_length=2000)
    name = forms.CharField(max_length=150, required=False)
    phone = forms.CharField(max_length=80, required=False)
    email = forms.EmailField(required=False)
    conversation_token = forms.CharField(max_length=1000, required=False)


def _can_use_widget(request, instance):
    if instance.client.is_paid_active and instance.status == "active" and instance.embed_enabled:
        return True
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return False
    return user.is_employee_or_admin() or instance.client.user_id == user.pk


def _rate_limited(request, slug, limit=40, window=60):
    return not consume_budget(f"widget:{slug}", request_identity(request), limit=limit, window=window)


@xframe_options_exempt
def widget(request, slug):
    instance = get_object_or_404(AIInstance.objects.select_related("client"), slug=slug)
    if not _can_use_widget(request, instance):
        raise Http404("Widget disabled")
    return render(request, "assistant_ai/widget.html", {"instance": instance})


@csrf_exempt
@require_POST
def widget_chat_api(request, slug):
    instance = get_object_or_404(AIInstance.objects.select_related("client"), slug=slug)
    if not _can_use_widget(request, instance):
        raise Http404("Widget unavailable")
    form = ChatForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": "Enter a message under 2,000 characters and valid contact details."}, status=400)
    data = form.cleaned_data
    # A numeric ID or a visitor-supplied ID is never proof of conversation ownership.
    token = data["conversation_token"]
    conversation = None
    if token:
        try:
            payload = signing.loads(token, salt=TOKEN_SALT, max_age=86400 * 7)
            conversation = Conversation.objects.get(pk=payload["conversation"], ai_instance=instance, visitor_id=payload["visitor"])
        except (signing.BadSignature, KeyError, TypeError, ValueError, Conversation.DoesNotExist):
            return JsonResponse({"error": "This chat session has expired. Start a new conversation.", "code": "session_expired"}, status=403)
    elif request.POST.get("conversation_id"):
        return JsonResponse({"error": "Start a new conversation to continue securely.", "code": "session_expired"}, status=403)
    if _rate_limited(request, slug):
        return JsonResponse({"error": "Too many messages. Please wait a minute and try again."}, status=429)
    contact = {
        "customer_name": data["name"] if instance.collect_name else "",
        "customer_phone": data["phone"] if instance.collect_phone else "",
        "customer_email": data["email"] if instance.collect_email else "",
    }
    if conversation is None:
        conversation = Conversation.objects.create(ai_instance=instance, visitor_id=str(uuid.uuid4()), channel="web", **contact)
        token = signing.dumps({"conversation": conversation.pk, "visitor": conversation.visitor_id}, salt=TOKEN_SALT)
    else:
        for field, value in contact.items():
            if value:
                setattr(conversation, field, value)
        conversation.save(update_fields=[*contact, "updated_at"])
    message = data["message"]
    Message.objects.create(conversation=conversation, sender="visitor", content=message)
    reply = generate_ai_reply(instance, conversation, message)
    Message.objects.create(conversation=conversation, sender="assistant", content=reply)
    conversation.save(update_fields=["updated_at"])
    if any(x in message.lower() for x in ["quote", "book", "appointment", "order", "urgent", "asap", "pricing", "call me"]) or any(contact.values()):
        capture_conversation_lead(instance, conversation, source="AI widget")
    return JsonResponse({"reply": reply, "conversation_token": token, "conversation_id": conversation.pk})
