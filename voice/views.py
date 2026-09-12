import hashlib
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.twiml.messaging_response import MessagingResponse

from clients.models import AIInstance, Integration
from assistant_ai.models import Conversation, Message
from assistant_ai.services import generate_ai_reply, capture_conversation_lead
from .models import CallLog, SMSLog, WebhookReceipt


def _production_enabled(instance):
    return instance.client.is_paid_active and instance.status == "active"


def _twilio_request_is_valid(request, instance=None):
    if not settings.VALIDATE_TWILIO_SIGNATURES:
        return True
    token = settings.TWILIO_AUTH_TOKEN
    if instance:
        integration = Integration.objects.filter(client=instance.client, integration_type="twilio", is_active=True).first()
        if integration:
            token = integration.get_credential("auth_token") or token
    if not token:
        return False
    return RequestValidator(token).validate(request.build_absolute_uri(), request.POST, request.META.get("HTTP_X_TWILIO_SIGNATURE", ""))


def _xml(response):
    return HttpResponse(str(response), content_type="text/xml")


def _receipt(key):
    digest = hashlib.sha256(key.encode()).hexdigest()
    WebhookReceipt.objects.get_or_create(key=digest)
    return WebhookReceipt.objects.select_for_update().get(pk=digest)


def _save_response(receipt, response):
    receipt.response = str(response)
    receipt.save(update_fields=["response"])
    return _xml(receipt.response)


def _gather(instance, call, turn):
    url = reverse("process_call", kwargs={"slug": instance.slug, "call_id": call.pk})
    return Gather(input="speech", action=f"{url}?turn={turn}", method="POST", speech_timeout="auto", timeout=5)


@csrf_exempt
@require_POST
def incoming_call(request, slug):
    instance = get_object_or_404(AIInstance.objects.select_related("client"), slug=slug)
    if not _twilio_request_is_valid(request, instance):
        return HttpResponse("Forbidden", status=403)
    sid = request.POST.get("CallSid", "")
    if not sid or len(sid) > 120:
        return HttpResponse("CallSid required", status=400)
    with transaction.atomic():
        receipt = _receipt(f"call:{instance.pk}:{sid}")
        if receipt.response:
            return _xml(receipt.response)
        response = VoiceResponse()
        if not instance.voice_enabled or not _production_enabled(instance):
            response.say("This AI receptionist is currently unavailable. Please contact the business directly.", voice="alice")
            return _save_response(receipt, response)
        conversation = Conversation.objects.create(ai_instance=instance, channel="voice", customer_phone=request.POST.get("From", "")[:80])
        call = CallLog.objects.create(ai_instance=instance, conversation=conversation, from_number=conversation.customer_phone, to_number=request.POST.get("To", "")[:80], call_sid=sid)
        gather = _gather(instance, call, 0)
        gather.say(instance.greeting or f"Thanks for calling {instance.client.business_name}. How can I help today?", voice="alice")
        response.append(gather)
        response.say("Sorry, I did not hear anything. Please call back later.", voice="alice")
        return _save_response(receipt, response)


@csrf_exempt
@require_POST
def process_call(request, slug, call_id):
    instance = get_object_or_404(AIInstance.objects.select_related("client"), slug=slug)
    if not _twilio_request_is_valid(request, instance):
        return HttpResponse("Forbidden", status=403)
    try:
        turn = int(request.GET.get("turn", "0"))
        if not 0 <= turn <= 50:
            raise ValueError
    except ValueError:
        return HttpResponse("Invalid call turn", status=400)
    with transaction.atomic():
        call = get_object_or_404(CallLog.objects.select_for_update(), pk=call_id, ai_instance=instance)
        if request.POST.get("CallSid") != call.call_sid:
            return HttpResponse("Forbidden", status=403)
        receipt = _receipt(f"turn:{call.pk}:{turn}")
        if receipt.response:
            return _xml(receipt.response)
        response = VoiceResponse()
        if not instance.voice_enabled or not _production_enabled(instance):
            response.say("This AI receptionist is currently unavailable.", voice="alice")
            return _save_response(receipt, response)
        speech = request.POST.get("SpeechResult", "").strip()[:2000]
        if speech:
            if not call.conversation_id:
                call.conversation = Conversation.objects.create(ai_instance=instance, channel="voice", customer_phone=call.from_number)
            convo = call.conversation
            Message.objects.create(conversation=convo, sender="visitor", content=speech)
            reply = generate_ai_reply(instance, convo, speech)
            Message.objects.create(conversation=convo, sender="assistant", content=reply)
            convo.save(update_fields=["updated_at"])
            call.transcript += f"\nCaller: {speech}\nAssistant: {reply}"
            call.status = "in_progress"
            call.save(update_fields=["conversation", "transcript", "status"])
            capture_conversation_lead(instance, convo, source="Voice AI call")
            response.say(reply[:1300], voice="alice")
        else:
            response.say("I did not catch that. Please try again.", voice="alice")
        if turn < 50:
            gather = _gather(instance, call, turn + 1)
            gather.say("Is there anything else I can help with?", voice="alice")
            response.append(gather)
        response.say("Thank you for calling. Goodbye.", voice="alice")
        return _save_response(receipt, response)


@csrf_exempt
@require_POST
def incoming_sms(request, slug):
    instance = get_object_or_404(AIInstance.objects.select_related("client"), slug=slug)
    if not _twilio_request_is_valid(request, instance):
        return HttpResponse("Forbidden", status=403)
    sid = request.POST.get("MessageSid", "")
    if not sid or len(sid) > 120:
        return HttpResponse("MessageSid required", status=400)
    from_number = request.POST.get("From", "")[:80]
    body = request.POST.get("Body", "").strip()[:2000]
    with transaction.atomic():
        receipt = _receipt(f"sms:{instance.pk}:{sid}")
        if receipt.response:
            return _xml(receipt.response)
        if not instance.sms_enabled or not _production_enabled(instance):
            reply = "Thanks for reaching out. This SMS assistant is currently unavailable."
        elif not body:
            reply = "Please send a text message describing what you need help with."
        else:
            # Serialize contact-session creation on this assistant across web workers.
            AIInstance.objects.select_for_update().get(pk=instance.pk)
            convo = Conversation.objects.filter(ai_instance=instance, channel="sms", customer_phone=from_number, updated_at__gte=timezone.now()-timedelta(hours=24)).first()
            if not convo:
                convo = Conversation.objects.create(ai_instance=instance, channel="sms", customer_phone=from_number)
            Message.objects.create(conversation=convo, sender="visitor", content=body)
            reply = generate_ai_reply(instance, convo, body)
            Message.objects.create(conversation=convo, sender="assistant", content=reply)
            convo.save(update_fields=["updated_at"])
            capture_conversation_lead(instance, convo, source="SMS AI")
        SMSLog.objects.create(ai_instance=instance, from_number=from_number, to_number=request.POST.get("To", "")[:80], body=body, response=reply, message_sid=sid)
        response = MessagingResponse()
        response.message(reply[:1500])
        return _save_response(receipt, response)
