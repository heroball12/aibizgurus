from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import VoiceResponse, Gather
from twilio.twiml.messaging_response import MessagingResponse
from clients.models import AIInstance
from assistant_ai.models import Conversation, Message
from assistant_ai.services import generate_ai_reply
from crm.models import Lead
from .models import CallLog, SMSLog


def _production_enabled(instance):
    return instance.client.is_paid_active and instance.status == "active"


def _twilio_request_is_valid(request):
    if not settings.VALIDATE_TWILIO_SIGNATURES:
        return True
    if not settings.TWILIO_AUTH_TOKEN:
        return False
    signature = request.META.get("HTTP_X_TWILIO_SIGNATURE", "")
    validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
    return validator.validate(request.build_absolute_uri(), request.POST, signature)


@csrf_exempt
def incoming_call(request, slug):
    if not _twilio_request_is_valid(request):
        return HttpResponse("Forbidden", status=403)
    instance = get_object_or_404(AIInstance, slug=slug)
    response = VoiceResponse()
    if not instance.voice_enabled or not _production_enabled(instance):
        response.say("This AI receptionist is currently unavailable. Please call the business directly.", voice="alice")
        return HttpResponse(str(response), content_type="text/xml")
    call = CallLog.objects.create(
        ai_instance=instance,
        from_number=request.POST.get("From", ""),
        to_number=request.POST.get("To", ""),
        call_sid=request.POST.get("CallSid", ""),
    )
    gather = Gather(input="speech", action=f"/voice/process/{instance.slug}/{call.pk}/", method="POST", speech_timeout="auto", timeout=5)
    gather.say(instance.greeting or f"Thanks for calling {instance.client.business_name}. How can I help today?", voice="alice")
    response.append(gather)
    response.say("Sorry, I did not hear anything. Please call back later.", voice="alice")
    return HttpResponse(str(response), content_type="text/xml")

@csrf_exempt
def process_call(request, slug, call_id):
    if not _twilio_request_is_valid(request):
        return HttpResponse("Forbidden", status=403)
    instance = get_object_or_404(AIInstance, slug=slug)
    if not instance.voice_enabled or not _production_enabled(instance):
        response = VoiceResponse()
        response.say("This AI receptionist is currently unavailable.", voice="alice")
        return HttpResponse(str(response), content_type="text/xml")
    call = get_object_or_404(CallLog, pk=call_id, ai_instance=instance)
    speech = request.POST.get("SpeechResult", "")
    call.transcript += f"\nCaller: {speech}"
    call.save()

    convo = Conversation.objects.create(ai_instance=instance, channel="voice", customer_phone=call.from_number)
    Message.objects.create(conversation=convo, sender="visitor", content=speech or "Caller did not speak.")
    reply = generate_ai_reply(instance, convo, speech or "The caller is on the phone.")
    Message.objects.create(conversation=convo, sender="assistant", content=reply)
    convo.save(update_fields=["updated_at"])

    Lead.objects.create(client=instance.client, ai_instance=instance, lead_type="client_customer", phone=call.from_number, source="Voice AI call", status="new", notes=f"Caller: {speech}\nAssistant: {reply}")

    response = VoiceResponse()
    response.say(reply[:1300], voice="alice")
    gather = Gather(input="speech", action=f"/voice/process/{instance.slug}/{call.pk}/", method="POST", speech_timeout="auto", timeout=5)
    gather.say("Is there anything else I can help with?", voice="alice")
    response.append(gather)
    response.say("Thank you. The team will follow up if needed. Goodbye.", voice="alice")
    return HttpResponse(str(response), content_type="text/xml")

@csrf_exempt
def incoming_sms(request, slug):
    if not _twilio_request_is_valid(request):
        return HttpResponse("Forbidden", status=403)
    instance = get_object_or_404(AIInstance, slug=slug)
    from_number = request.POST.get("From", "")
    body = request.POST.get("Body", "")
    if not instance.sms_enabled or not _production_enabled(instance):
        reply = "Thanks for reaching out. This SMS assistant is currently unavailable."
    else:
        convo = Conversation.objects.create(ai_instance=instance, channel="sms", customer_phone=from_number)
        Message.objects.create(conversation=convo, sender="visitor", content=body)
        reply = generate_ai_reply(instance, convo, body)
        Message.objects.create(conversation=convo, sender="assistant", content=reply)
        convo.save(update_fields=["updated_at"])
        Lead.objects.create(client=instance.client, ai_instance=instance, lead_type="client_customer", phone=from_number, source="SMS AI", status="new", notes=f"SMS: {body}\nReply: {reply}")
    SMSLog.objects.create(ai_instance=instance, from_number=from_number, to_number=request.POST.get("To", ""), body=body, response=reply, message_sid=request.POST.get("MessageSid", ""))
    twiml = MessagingResponse()
    twiml.message(reply[:1500])
    return HttpResponse(str(twiml), content_type="text/xml")
