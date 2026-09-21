from django import forms
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from assistant_ai.services import PlatformAIService
from assistant_ai import concierge_context
from .demo_profiles import LEGACY_SLUGS, resolve_profile, sample_reply, system_prompt
from .rate_limits import consume_budget, request_identity
from . import cannabis_knowledge


def cannabis_library(request):
    data = cannabis_knowledge.library()
    topics = [{**t, "references": [data["sources"][key] for key in t["sources"]]} for t in data["topics"]]
    query = request.GET.get('q', '').strip()[:100]
    if query:
        words = cannabis_knowledge.normalize(query).split()
        topics = [t for t in topics if all(word in cannabis_knowledge.normalize(' '.join([t['title'], t['summary'], *t['keywords']])) for word in words)]
    return render(request, "core/cannabis_knowledge.html", {"library": data, "topics": topics, "query": query, "topic_count": len(data['topics']), "source_count": len(data['sources'])})


class DemoChatForm(forms.Form):
    message = forms.CharField(max_length=1000)


@require_POST
@never_cache
def demo_chat(request):
    selected = request.POST.get("industry") or request.POST.get("scenario", "")
    profile = resolve_profile(selected)
    if not profile:
        return JsonResponse({"error": "Choose an industry from the demo list."}, status=400)
    # Accept the previous demo's identifiers for browsers with cached older assets.
    key = selected if selected in LEGACY_SLUGS else profile["slug"]
    history = request.session.get("demo_history", {})
    aliases = [alias for alias, slug in LEGACY_SLUGS.items() if slug == profile["slug"]]
    turns = history.get(key, history.get(profile["slug"], next((history[a] for a in aliases if a in history), [])))[-10:]
    for old_key in [profile["slug"], *aliases]:
        history.pop(old_key, None)
    if request.POST.get("reset") == "1":
        request.session["demo_history"] = history
        return JsonResponse({"reset": True, "industry": profile["slug"]})
    form = DemoChatForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": "Enter a message of 1–1,000 characters."}, status=400)
    if not consume_budget("public-demo", request_identity(request), limit=30, window=3600):
        return JsonResponse({"error": "You’ve reached this demo’s message limit. Try again later or book a growth consultation."}, status=429)
    message = form.cleaned_data["message"]
    transfer = concierge_context.handoff(request.session, request.POST.get("handoff"), profile["slug"])
    topics = cannabis_knowledge.topics_for(message, turns) if profile['slug'] == 'cannabis' else []
    fallback = cannabis_knowledge.sample_answer(message, turns, topics) if profile['slug'] == 'cannabis' else sample_reply(profile, message)
    reply, meta = fallback, {"status": "fallback"}
    if settings.PLATFORM_OPENAI_API_KEY and consume_budget("demo-ai-daily", "platform", limit=getattr(settings, "DEMO_DAILY_AI_LIMIT", 100), window=86400):
        service = PlatformAIService(assistant_role="public_demo")
        service.max_retries = 0
        reply, meta = service.chat(
            messages=[{"role": "system", "content": system_prompt(profile) + (cannabis_knowledge.text_reference(topics) if profile['slug'] == 'cannabis' else '') + concierge_context.prompt(transfer["context"] if transfer else {})}, *({"role": t["role"], "content": t["content"]} for t in turns), {"role": "user", "content": message}],
            fallback=fallback, metadata={"industry": profile["slug"]},
        )
    mode = "ai" if meta.get("status") == "success" else "guided"
    topic_ids = [t['id'] for t in topics]
    history[key] = [*turns, {"role": "user", "content": message}, {"role": "assistant", "content": reply, "knowledge_topics": topic_ids}][-12:]
    # Bound the anonymous session, even if a visitor explores the whole catalog.
    request.session["demo_history"] = dict(list(history.items())[-8:])
    return JsonResponse({"reply": reply, "industry": profile["slug"], "mode": mode, "knowledge_topics": topic_ids})
