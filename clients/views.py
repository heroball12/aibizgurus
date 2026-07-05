from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from core.permissions import employee_required
from django.shortcuts import get_object_or_404, redirect, render
from .models import ClientAccount, BusinessProfile, AIInstance, Integration
from .forms import BusinessProfileForm, AIInstanceForm, ActivatedAIInstanceForm, IntegrationForm
from crm.models import Lead
from assistant_ai.models import Conversation

def get_client_for_user(user):
    return user.client_accounts.order_by("-created_at").first()

@login_required
def portal_home(request):
    if request.user.is_employee_or_admin():
        return redirect("owner_dashboard" if request.user.is_owner() else "ops_dashboard")
    client = get_client_for_user(request.user)
    if not client:
        messages.info(request, "No client account found yet.")
        return redirect("home")
    paid_active = client.is_paid_active
    locked_features = [
        {"name": "Publish website embed", "description": "Add your assistant to your live website.", "url": "billing_home"},
        {"name": "Live OpenAI responses", "description": "Use full AI replies trained on your business details.", "url": "billing_home"},
        {"name": "Voice AI calling", "description": "Connect a Twilio number for phone conversations.", "url": "billing_home"},
        {"name": "SMS automation", "description": "Reply to texts and missed-call follow-ups.", "url": "billing_home"},
        {"name": "Lead alerts", "description": "Send new lead notifications to your team.", "url": "billing_home"},
        {"name": "CRM exports", "description": "Export and manage your lead pipeline.", "url": "billing_home"},
    ]
    return render(request, "clients/portal_home.html", {
        "client": client,
        "assistants": client.ai_instances.all(),
        "leads": Lead.objects.filter(client=client, lead_type="client_customer").order_by("-created_at")[:10],
        "conversations": Conversation.objects.filter(ai_instance__client=client).select_related("ai_instance").order_by("-updated_at", "-created_at")[:10],
        "paid_active": paid_active,
        "locked_features": locked_features,
    })

@login_required
def business_profile(request):
    client = get_client_for_user(request.user)
    if not client:
        messages.error(request, "A client account is required.")
        return redirect("portal_home")
    profile, _ = BusinessProfile.objects.get_or_create(client=client)
    if request.method == "POST":
        form = BusinessProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Business profile saved.")
            return redirect("business_profile")
    else:
        form = BusinessProfileForm(instance=profile)
    return render(request, "clients/business_profile.html", {"client": client, "form": form})

@login_required
def assistant_settings(request, pk):
    instance = get_object_or_404(AIInstance, pk=pk)
    if not request.user.is_employee_or_admin() and instance.client.user != request.user:
        messages.error(request, "Access denied.")
        return redirect("portal_home")
    can_publish = instance.client.can_publish_assistants
    form_class = ActivatedAIInstanceForm if request.user.is_employee_or_admin() or can_publish else AIInstanceForm
    if request.method == "POST":
        form = form_class(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "AI assistant saved.")
            return redirect("assistant_settings", pk=instance.pk)
    else:
        form = form_class(instance=instance)
    return render(request, "clients/assistant_settings.html", {
        "instance": instance,
        "form": form,
        "iframe": instance.iframe_code(settings.PUBLIC_BASE_URL),
        "base_url": settings.PUBLIC_BASE_URL,
        "can_publish": can_publish,
    })

@login_required
def integrations(request):
    client = get_client_for_user(request.user)
    if not client:
        messages.error(request, "A client account is required.")
        return redirect("portal_home")
    if request.method == "POST":
        existing = Integration.objects.filter(
            client=client,
            integration_type=request.POST.get("integration_type", ""),
            name=request.POST.get("name", "Default"),
        ).first()
        form = IntegrationForm(request.POST, instance=existing)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.client = client
            obj.save()
            messages.success(request, "Integration saved.")
            return redirect("integrations")
    else:
        form = IntegrationForm(initial={"integration_type": "openai", "name": "Default"})
    return render(request, "clients/integrations.html", {"client": client, "form": form, "items": client.integrations.all()})

@login_required
def client_leads(request):
    client = get_client_for_user(request.user)
    if not client or not client.is_paid_active:
        messages.info(request, "Activate your account to open the production lead inbox.")
        return redirect("billing_home")
    return render(request, "clients/client_leads.html", {
        "client": client,
        "leads": Lead.objects.filter(client=client, lead_type="client_customer"),
    })

@login_required
def client_conversations(request):
    client = get_client_for_user(request.user)
    if not client:
        messages.error(request, "A client account is required.")
        return redirect("portal_home")
    conversations = (
        Conversation.objects.filter(ai_instance__client=client)
        .select_related("ai_instance")
        .order_by("-updated_at", "-created_at")
    )
    return render(request, "clients/client_conversations.html", {
        "client": client,
        "conversations": conversations,
        "paid_active": client.is_paid_active,
    })


@login_required
def client_conversation_detail(request, pk):
    client = get_client_for_user(request.user)
    if not client:
        messages.error(request, "A client account is required.")
        return redirect("portal_home")
    conversation = get_object_or_404(
        Conversation.objects.select_related("ai_instance", "ai_instance__client"),
        pk=pk,
        ai_instance__client=client,
    )
    return render(request, "clients/conversation_detail.html", {
        "client": client,
        "conversation": conversation,
        "conversation_messages": conversation.messages.order_by("created_at"),
        "is_staff_view": False,
        "paid_active": client.is_paid_active,
    })


@login_required
def demo_setup_guide(request):
    if request.user.is_employee_or_admin():
        return redirect("owner_dashboard" if request.user.is_owner() else "ops_dashboard")
    client = request.user.client_accounts.order_by("-created_at").first()
    assistant = client.ai_instances.order_by("-created_at").first() if client else None
    return render(request, "clients/demo_setup_guide.html", {"client": client, "assistant": assistant})


@employee_required
def ops_client_detail(request, client_id):
    client = get_object_or_404(ClientAccount, pk=client_id)
    assistants = client.ai_instances.order_by("-created_at")
    leads = Lead.objects.filter(client=client, lead_type="client_customer").order_by("-created_at")
    conversations = Conversation.objects.filter(ai_instance__client=client).select_related("ai_instance").order_by("-updated_at", "-created_at")
    return render(request, "clients/ops_client_detail.html", {
        "client": client,
        "assistants": assistants,
        "leads": leads,
        "conversations": conversations,
    })


@employee_required
def ops_conversation_detail(request, client_id, conversation_id):
    client = get_object_or_404(ClientAccount, pk=client_id)
    conversation = get_object_or_404(
        Conversation.objects.select_related("ai_instance", "ai_instance__client"),
        pk=conversation_id,
        ai_instance__client=client,
    )
    return render(request, "clients/conversation_detail.html", {
        "client": client,
        "conversation": conversation,
        "conversation_messages": conversation.messages.order_by("created_at"),
        "is_staff_view": True,
        "paid_active": client.is_paid_active,
    })
