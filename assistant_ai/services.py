import logging
import json
from django.conf import settings
from django.utils import timezone
from openai import OpenAI
from clients.models import Integration
from .models import UsageRecord

logger = logging.getLogger(__name__)


class PlatformAIService:
    """Central server-side OpenAI gateway for platform features.

    This service intentionally stores usage metadata only. It does not store
    prompts, API keys, authorization headers, or raw model responses.
    """

    def __init__(self, *, api_key=None, user=None, client_account=None, ai_instance=None, assistant_role="client_assistant"):
        self.api_key = api_key if api_key is not None else settings.PLATFORM_OPENAI_API_KEY
        self.user = user
        self.client_account = client_account
        self.ai_instance = ai_instance
        self.assistant_role = assistant_role
        self.timeout = getattr(settings, "OPENAI_REQUEST_TIMEOUT", 20)
        self.max_retries = getattr(settings, "OPENAI_MAX_RETRIES", 1)

    def _record_usage(self, *, model="", response=None, status="success", error_code="", metadata=None):
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0
        try:
            UsageRecord.objects.create(
                user=self.user if getattr(self.user, "is_authenticated", False) else None,
                client=self.client_account,
                ai_instance=self.ai_instance,
                assistant_role=self.assistant_role,
                model=model or "",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                status=status,
                error_code=str(error_code or "")[:120],
                metadata=metadata or {},
            )
        except Exception:
            logger.exception("AI usage recording failed")

    def daily_limit_reached(self):
        limit = getattr(settings, "OPENAI_DAILY_USAGE_LIMIT", 500)
        if not limit:
            return False
        start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        records = UsageRecord.objects.filter(created_at__gte=start, assistant_role=self.assistant_role)
        if self.user and getattr(self.user, "is_authenticated", False):
            records = records.filter(user=self.user)
        return records.count() >= limit

    def chat(self, *, messages, model=None, temperature=0.35, fallback="", metadata=None):
        model = model or getattr(settings, "OPENAI_CHAT_MODEL", settings.OPENAI_MODEL)
        if not self.api_key:
            self._record_usage(model=model, status="fallback", error_code="missing_api_key", metadata=metadata)
            return fallback, {"status": "fallback", "reason": "missing_api_key"}
        if self.daily_limit_reached():
            self._record_usage(model=model, status="blocked", error_code="daily_limit", metadata=metadata)
            return fallback, {"status": "blocked", "reason": "daily_limit"}

        last_error = None
        for attempt in range(max(1, self.max_retries + 1)):
            try:
                client = OpenAI(api_key=self.api_key)
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=float(temperature),
                    timeout=self.timeout,
                )
                content = response.choices[0].message.content or fallback
                self._record_usage(model=model, response=response, status="success", metadata={**(metadata or {}), "attempt": attempt + 1})
                return content, {"status": "success"}
            except Exception as exc:
                last_error = exc
                logger.warning("OpenAI chat request failed for role=%s attempt=%s", self.assistant_role, attempt + 1)

        self._record_usage(model=model, status="error", error_code=type(last_error).__name__ if last_error else "unknown", metadata=metadata)
        return fallback, {"status": "error", "reason": type(last_error).__name__ if last_error else "unknown"}

    def structured_json(self, *, messages, schema_hint=None, model=None, temperature=0, fallback=None, metadata=None):
        prompt_messages = list(messages)
        if schema_hint:
            prompt_messages.append({
                "role": "system",
                "content": f"Return only valid JSON matching this shape. Do not include markdown: {schema_hint}",
            })
        content, meta = self.chat(
            messages=prompt_messages,
            model=model or getattr(settings, "OPENAI_CLASSIFICATION_MODEL", settings.OPENAI_MODEL),
            temperature=temperature,
            fallback=json.dumps(fallback or {}),
            metadata=metadata,
        )
        try:
            return json.loads(content), meta
        except json.JSONDecodeError:
            return fallback or {}, {"status": "fallback", "reason": "invalid_json"}

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

    history = []
    for msg in conversation.messages.order_by("-created_at")[:10][::-1]:
        if msg.sender == "system":
            continue
        role = "assistant" if msg.sender == "assistant" else "user"
        history.append({"role": role, "content": msg.content})
    messages = [{"role": "system", "content": build_system_prompt(ai_instance)}] + history
    if not history or history[-1] != {"role": "user", "content": user_message}:
        messages.append({"role": "user", "content": user_message})
    service = PlatformAIService(
        api_key=api_key,
        client_account=ai_instance.client,
        ai_instance=ai_instance,
        assistant_role="client_assistant",
    )
    reply, _ = service.chat(
        model=ai_instance.model or settings.OPENAI_CHAT_MODEL,
        messages=messages,
        temperature=0.35,
        fallback=fallback_reply(ai_instance, user_message),
        metadata={"conversation_id": conversation.pk},
    )
    return reply
