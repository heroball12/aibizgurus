import logging
from django.conf import settings
from openai import OpenAI
from clients.models import Integration

logger = logging.getLogger(__name__)

def get_client_openai_key(ai_instance):
    integration = Integration.objects.filter(
        client=ai_instance.client,
        integration_type="openai",
        is_active=True,
    ).first()
    if integration:
        return integration.get_credential("api_key") or ""
    return ""

def choose_openai_key(ai_instance):
    if ai_instance.openai_api_mode == "client":
        return get_client_openai_key(ai_instance)
    if ai_instance.openai_api_mode == "platform":
        return settings.PLATFORM_OPENAI_API_KEY
    return ""

def build_system_prompt(ai_instance):
    profile = getattr(ai_instance.client, "profile", None)
    knowledge = profile.as_knowledge_text() if profile else ""
    docs = "\n\n".join([d.content for d in ai_instance.knowledge_documents.all()[:10]])
    return (
        f"You are {ai_instance.name}, an AI receptionist for {ai_instance.client.business_name}.\n"
        f"Tone: {ai_instance.tone}\n\n"
        f"Core instructions:\n{ai_instance.system_prompt or 'Answer questions, capture leads, and route serious customers to staff.'}\n\n"
        f"Business knowledge:\n{knowledge}\n\n"
        f"Additional knowledge:\n{docs}\n\n"
        "Lead capture: When a visitor seems interested, collect name, phone, email if needed, what they need, urgency, and best follow-up time. "
        "Never claim an appointment, order, price, legal/medical result, or emergency service is confirmed unless the business info explicitly says so."
    )

def fallback_reply(ai_instance, user_message):
    text = (user_message or "").lower()
    name = ai_instance.client.business_name
    if any(x in text for x in ["price", "cost", "quote", "how much"]):
        return f"Pricing can depend on the details. I can collect your info and have {name} follow up with an accurate quote. What do you need help with?"
    if any(x in text for x in ["hours", "open", "close"]):
        return f"I can help with hours and availability. What service or question can I help you with today?"
    if any(x in text for x in ["book", "appointment", "schedule", "order"]):
        return "I can help start that request. What is your name, phone number, and preferred day/time?"
    if any(x in text for x in ["urgent", "emergency", "asap", "now"]):
        return "Got it. Please send your name, phone number, location, and what happened. I’ll mark this as urgent."
    return f"Thanks. I can answer questions or get your info to {name}. What would you like help with?"

def generate_ai_reply(ai_instance, conversation, user_message):
    if ai_instance.status in {"paused", "offline"}:
        return "This assistant is currently offline. Please contact the business directly."

    api_key = choose_openai_key(ai_instance)
    if not api_key:
        return fallback_reply(ai_instance, user_message)

    try:
        client = OpenAI(api_key=api_key)
        history = []
        for msg in conversation.messages.order_by("-created_at")[:10][::-1]:
            if msg.sender == "system":
                continue
            role = "assistant" if msg.sender == "assistant" else "user"
            history.append({"role": role, "content": msg.content})
        messages = [{"role": "system", "content": build_system_prompt(ai_instance)}] + history
        if not history or history[-1] != {"role": "user", "content": user_message}:
            messages.append({"role": "user", "content": user_message})
        response = client.chat.completions.create(
            model=ai_instance.model or settings.OPENAI_MODEL,
            messages=messages,
            temperature=0.35,
        )
        return response.choices[0].message.content or fallback_reply(ai_instance, user_message)
    except Exception:
        logger.exception('OpenAI generation failed for assistant %s', ai_instance.pk)
        return fallback_reply(ai_instance, user_message)
