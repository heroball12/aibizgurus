from django.contrib.auth import login
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.views import View
from .forms import SignupForm
from core.models import IndustryTemplate
from core.seed import safe_seed_industries
from core.industry_options import get_industry_options, get_option_by_slug, ensure_template_for_option
from clients.models import ClientAccount, BusinessProfile, AIInstance

def signup(request):
    # Real path: industries live in the database and are used to create the demo assistant.
    # If the table is empty, seed it immediately for this local/dev request.
    if IndustryTemplate.objects.count() == 0:
        safe_seed_industries()

    db_templates = list(IndustryTemplate.objects.all().order_by("category", "name"))

    # Emergency fallback only: the selected signup still creates a real DB template
    # before the assistant is created.
    if db_templates:
        templates = db_templates
        template_source = "database"
    else:
        templates, template_source = get_industry_options()

    selected_industry_slug = request.GET.get("industry_slug", "")
    selected_template, selected_source = get_option_by_slug(selected_industry_slug) if selected_industry_slug else (None, "none")

    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            slug = form.cleaned_data["industry_slug"]
            template = IndustryTemplate.objects.filter(slug=slug).first()
            if not template:
                selected_option, _ = get_option_by_slug(slug)
                template = ensure_template_for_option(selected_option) if selected_option else None

            if not template:
                form.add_error("industry_slug", "Choose a valid industry template.")
            else:
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.role = "client"
                    user.save()
                    client = ClientAccount.objects.create(
                        user=user,
                        business_name=form.cleaned_data["business_name"],
                        industry_template=template,
                        industry=template.name,
                        contact_email=user.email,
                        status="onboarding",
                        activation_status="demo",
                    )
                    BusinessProfile.objects.create(client=client)
                    AIInstance.objects.create_from_template(client, template)
                login(request, user)
                messages.success(request, "Account created. Your AI assistant draft is ready.")
                return redirect("portal_home")
    else:
        form = SignupForm(initial={"industry_slug": selected_industry_slug})

    return render(request, "accounts/signup.html", {
        "form": form,
        "templates": templates,
        "template_count": len(templates),
        "template_source": template_source,
        "selected_industry_slug": selected_industry_slug,
        "selected_template": selected_template,
    })


class RoleAwareLoginView(LoginView):
    template_name = "accounts/login.html"

    def get_success_url(self):
        user = self.request.user
        if user.is_owner():
            return "/owner/"
        if user.is_employee_or_admin():
            return "/ops/"
        return "/portal/"


class FriendlyLogoutView(View):
    def get(self, request):
        logout(request)
        return redirect("home")

    def post(self, request):
        logout(request)
        return redirect("home")
