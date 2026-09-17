from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from .models import IndustryTemplate
from .seed import safe_seed_industries
from .industry_options import get_industry_options
from .forms import ConsultationRequestForm
from .landing_film import landing_film_assets
from .catalog import PRICING_PLANS
from crm.models import Lead
from clients.models import ClientAccount, AIInstance

SOLUTIONS = [
    {
        "slug": "ai-employees",
        "name": "AI Employees",
        "headline": "Role-based AI teammates that recover revenue and handle repetitive work.",
        "summary": "Deploy AI Receptionists, Sales Reps, Appointment Setters, Support Specialists, Review Managers, and Marketing Assistants around the workflows that make money.",
        "benefits": ["Recover missed calls and chats", "Speed up lead follow-up", "Automate repetitive customer workflows"],
        "use_cases": ["Inbound lead handling", "Appointment booking", "Follow-up sequences", "Customer support triage"],
        "how_it_works": ["Map the revenue workflow", "Train the AI Employee on your offers", "Connect the channels", "Review results in your dashboard"],
    },
    {
        "slug": "ai-chatbots",
        "name": "AI Chatbots",
        "headline": "Industry-specific website assistants that answer questions and capture leads.",
        "summary": "Turn website visitors into qualified opportunities with industry templates, business knowledge, fallback replies, and lead capture.",
        "benefits": ["Answer common questions 24/7", "Capture qualified leads", "Reduce repetitive front-desk work"],
        "use_cases": ["Website chat", "Service questions", "Quote requests", "FAQ automation"],
        "how_it_works": ["Choose an industry", "Customize business info", "Preview the assistant", "Publish the embed"],
    },
    {
        "slug": "voice-ai",
        "name": "Voice AI",
        "headline": "Phone-ready AI reception workflows for missed calls and high-intent customers.",
        "summary": "Use voice AI to capture caller details, route urgent requests, and support customers when your team is busy.",
        "benefits": ["Reduce missed revenue", "Capture caller details", "Route urgent opportunities"],
        "use_cases": ["Missed-call coverage", "After-hours intake", "Appointment requests", "Lead qualification"],
        "how_it_works": ["Connect Twilio", "Design call flows", "Capture lead context", "Notify the team"],
    },
    {
        "slug": "automation",
        "name": "Business Automation",
        "headline": "Automate the busywork between lead, appointment, follow-up, and sale.",
        "summary": "Connect intake, follow-up, CRM updates, review requests, and internal handoffs so opportunities do not leak.",
        "benefits": ["Save team hours", "Standardize follow-up", "Reduce manual errors"],
        "use_cases": ["Lead routing", "Follow-up reminders", "Review requests", "CRM updates"],
        "how_it_works": ["Audit manual work", "Build the workflow", "Connect tools", "Track outcomes"],
    },
    {
        "slug": "websites",
        "name": "Websites",
        "headline": "Conversion-focused websites built to turn attention into booked revenue.",
        "summary": "Pair beautiful pages with AI intake, clear calls-to-action, and lead capture systems.",
        "benefits": ["Improve conversion", "Clarify the offer", "Support AI-powered intake"],
        "use_cases": ["Service websites", "Landing pages", "Demo funnels", "Campaign pages"],
        "how_it_works": ["Clarify offer", "Design conversion pages", "Install AI assistant", "Measure leads"],
    },
    {
        "slug": "marketing",
        "name": "Marketing + SEO",
        "headline": "Growth systems that create demand and convert it faster.",
        "summary": "Use SEO, campaigns, content, and AI follow-up to get more qualified customers into your pipeline.",
        "benefits": ["Create more demand", "Improve lead quality", "Convert faster"],
        "use_cases": ["Local SEO", "Campaign landing pages", "Review growth", "Lead nurture"],
        "how_it_works": ["Find demand gaps", "Build campaigns", "Add AI follow-up", "Optimize monthly"],
    },
    {
        "slug": "crm-integrations",
        "name": "CRM Integrations",
        "headline": "Keep every captured opportunity organized and actionable.",
        "summary": "Route AI-captured leads and conversation context into the systems your team already uses.",
        "benefits": ["Cleaner pipeline", "Less copy/paste", "Better handoffs"],
        "use_cases": ["CRM sync", "Lead alerts", "Conversation notes", "Pipeline routing"],
        "how_it_works": ["Audit your tools", "Map fields", "Connect workflows", "Review activity"],
    },
    {
        "slug": "consulting",
        "name": "AI Consulting",
        "headline": "Executive AI strategy for revenue teams that want practical outcomes.",
        "summary": "Identify where AI can increase speed, reduce waste, recover revenue, and unlock scalable operations.",
        "benefits": ["Prioritize high-ROI use cases", "Avoid expensive distractions", "Create an implementation roadmap"],
        "use_cases": ["AI readiness audits", "Workflow design", "Vendor strategy", "Team enablement"],
        "how_it_works": ["Assess business goals", "Map bottlenecks", "Recommend AI workflows", "Plan implementation"],
    },
]

AI_EMPLOYEES = [
    {
        "name": "AI Receptionist",
        "description": "Answers inbound questions, captures caller or website visitor details, and routes urgent opportunities.",
        "benefits": ["Missed-call recovery", "After-hours coverage", "Lead capture"],
        "industries": "Home services, medical offices, law firms, restaurants",
        "workflow": "Greet → qualify need → collect contact details → route to staff",
        "example": "A homeowner asks for emergency service and the AI captures location, urgency, and phone number.",
    },
    {
        "name": "AI Sales Representative",
        "description": "Responds quickly to interested prospects and moves them toward quotes, appointments, or consultations.",
        "benefits": ["Faster follow-up", "Better qualification", "More booked calls"],
        "industries": "B2B services, agencies, contractors, real estate",
        "workflow": "Understand interest → ask qualifying questions → recommend next step → book handoff",
        "example": "A prospect asks about pricing and the AI qualifies budget, timeline, and project need.",
    },
    {
        "name": "AI Appointment Setter",
        "description": "Collects scheduling details and prepares clean booking requests for the team.",
        "benefits": ["More appointment requests", "Cleaner intake", "Less back-and-forth"],
        "industries": "Med spas, dentists, fitness studios, clinics",
        "workflow": "Confirm service → collect preferred times → gather contact info → send request",
        "example": "A customer wants a consultation next week and the AI captures availability and contact details.",
    },
    {
        "name": "AI Customer Support",
        "description": "Handles repetitive questions using business knowledge while escalating sensitive issues.",
        "benefits": ["Fewer repetitive tickets", "Faster answers", "Better customer experience"],
        "industries": "Retail, SaaS, healthcare, professional services",
        "workflow": "Answer known questions → clarify details → escalate when needed",
        "example": "A customer asks about policies, hours, or service areas and gets a reliable answer instantly.",
    },
    {
        "name": "AI Follow-Up Specialist",
        "description": "Keeps leads warm with structured follow-up so opportunities do not disappear.",
        "benefits": ["Less lead leakage", "More re-engagement", "Consistent nurture"],
        "industries": "Sales teams, home services, clinics, agencies",
        "workflow": "Identify lead stage → send next message → capture response → notify staff",
        "example": "A quote request goes quiet and the AI prompts the customer for decision timing.",
    },
    {
        "name": "AI Review Manager",
        "description": "Helps request reviews, identify unhappy customers, and support reputation growth.",
        "benefits": ["More reviews", "Better reputation", "Service recovery"],
        "industries": "Local services, restaurants, healthcare, wellness",
        "workflow": "Ask for feedback → route issues privately → request public reviews",
        "example": "A satisfied customer receives a friendly review request after service is completed.",
    },
    {
        "name": "AI Marketing Assistant",
        "description": "Supports campaigns, content ideas, offer testing, and growth follow-up.",
        "benefits": ["More consistent campaigns", "Faster content", "Better lead nurture"],
        "industries": "Local businesses, agencies, professional services",
        "workflow": "Plan campaign → draft content → route leads → review performance",
        "example": "The AI drafts a seasonal promotion and routes interested replies to the sales team.",
    },
]

def home(request):
    if not IndustryTemplate.objects.exists():
        safe_seed_industries()
    industries, industry_source = get_industry_options()
    return render(request, "core/home.html", {
        "industries": industries[:24],
        "industry_count": len(industries),
        "industry_source": industry_source,
        "solutions": SOLUTIONS,
        "ai_employees": AI_EMPLOYEES[:4],
        "arrival_film": landing_film_assets(),
    })


def healthz(request):
    from django.db import connections, DatabaseError
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def robots_txt(request):
    base_url = settings.PUBLIC_BASE_URL.rstrip("/")
    lines = [
        "User-agent: *",
        "Allow: /",
        f"Sitemap: {base_url}{reverse('sitemap_xml')}",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


def sitemap_xml(request):
    base_url = settings.PUBLIC_BASE_URL.rstrip("/")
    url_names = [
        "home",
        "solutions",
        "ai_employees",
        "industries",
        "demo",
        "pricing",
        "case_studies",
        "growth_assessment",
    ]
    paths = [reverse(name) for name in url_names]
    for solution in SOLUTIONS:
        paths.append(reverse("solution_detail", kwargs={"slug": solution["slug"]}))
    body = "\n".join(
        f"  <url><loc>{base_url}{path}</loc></url>"
        for path in paths
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}\n</urlset>\n'
    return HttpResponse(xml, content_type="application/xml")


def page_not_found(request, exception):
    return render(request, "404.html", status=404)


def server_error(request):
    return render(request, "500.html", status=500)

def industries(request):
    if not IndustryTemplate.objects.exists():
        safe_seed_industries()
    industry_items, industry_source = get_industry_options()
    groups = {}
    for item in industry_items:
        groups.setdefault(item.category or "Other", []).append(item)
    return render(request, "core/industries.html", {
        "groups": groups,
        "industry_count": len(industry_items),
        "industry_source": industry_source,
    })

def demo(request):
    from django.conf import settings
    from .demo_profiles import FEATURED, LEGACY_SLUGS, profiles
    from assistant_ai.demo_video import available_profiles
    from assistant_ai import concierge_context
    if not IndustryTemplate.objects.exists():
        safe_seed_industries()
    items = profiles()
    transfer = concierge_context.handoff(request.session, request.GET.get("handoff"))
    video_profiles = available_profiles()
    for item in items:
        item["video_available"] = item["slug"] in video_profiles
        if transfer and item["slug"] == transfer["industry"]:
            item["greeting"] = concierge_context.greeting(item, transfer["context"])
    public_items = [{k: v for k, v in item.items() if k not in {"facts", "escalation"}} for item in items]
    history = {LEGACY_SLUGS.get(key, key): value for key, value in request.session.get("demo_history", {}).items()}
    response = render(request, "core/demo.html", {
        "demo_industries": public_items,
        "featured_industries": [p for slug in FEATURED for p in public_items if p["slug"] == slug],
        "demo_categories": sorted({p["category"] for p in items}),
        "industry_count": len(items), "demo_history": history,
        "demo_config": {"aiAvailable": bool(settings.PLATFORM_OPENAI_API_KEY), "handoff": {"id": transfer["id"], "industry": transfer["industry"]} if transfer else None},
    })
    response["Cache-Control"] = "private, no-store"
    return response

def solutions(request):
    return render(request, "core/solutions.html", {"solutions": SOLUTIONS})

def solution_detail(request, slug):
    solution = next((item for item in SOLUTIONS if item["slug"] == slug), None)
    if not solution:
        raise Http404("Solution not found")
    return render(request, "core/solution_detail.html", {"solution": solution, "solutions": SOLUTIONS})

def ai_employees(request):
    return render(request, "core/ai_employees.html", {"employees": AI_EMPLOYEES})

def pricing(request):

    return render(request, "core/pricing.html", {"plans": PRICING_PLANS})

def case_studies(request):
    return render(request, "core/case_studies.html")

from django.db import transaction
from .rate_limits import consume_budget, request_identity


@transaction.atomic
def growth_assessment(request):
    if request.method == "POST":
        form = ConsultationRequestForm(request.POST)
        if not consume_budget("consultation", request_identity(request), limit=5, window=3600):
            form.add_error(None, "Too many requests. Please try again later or use the calendar above.")
        if not form.errors and form.is_valid():
            obj = form.save()
            Lead.objects.create(
                lead_type="internal_sales",
                name=obj.name,
                business_name=obj.business_name,
                phone=obj.phone,
                email=obj.email,
                industry=obj.industry,
                source="AI Business Growth Assessment",
                status="new",
                notes=obj.message,
            )
            messages.success(request, "Assessment request received. We will review your growth opportunities and follow up shortly.")
            return redirect("growth_assessment")
    else:
        form = ConsultationRequestForm()
    return render(request, "core/growth_assessment.html", {"form": form})

@transaction.atomic
def consultation_request(request):
    if request.method == "POST":
        form = ConsultationRequestForm(request.POST)
        if not consume_budget("consultation", request_identity(request), limit=5, window=3600):
            form.add_error(None, "Too many requests. Please try again later or use the calendar above.")
        if not form.errors and form.is_valid():
            obj = form.save()
            Lead.objects.create(
                lead_type="internal_sales",
                name=obj.name,
                business_name=obj.business_name,
                phone=obj.phone,
                email=obj.email,
                industry=obj.industry,
                source="Unsupported industry request",
                status="new",
                notes=obj.message,
            )
            messages.success(request, "Request received. We added it to the CRM.")
            return redirect("industries")
    else:
        form = ConsultationRequestForm()
    return render(request, "core/consultation_request.html", {"form": form})

@login_required
def ops_dashboard(request):
    if not request.user.is_employee_or_admin():
        messages.error(request, "Employee access required.")
        return redirect("portal_home")
    internal_leads = Lead.objects.filter(lead_type="internal_sales", archived=False)
    if not (request.user.is_superuser or getattr(request.user, "role", "") in {"admin", "owner"}):
        internal_leads = internal_leads.filter(assigned_to=request.user)
    context = {
        "clients": ClientAccount.objects.select_related("user").order_by("-created_at")[:20],
        "client_count": ClientAccount.objects.count(),
        "assistant_count": AIInstance.objects.count(),
        "lead_count": internal_leads.count(),
        "new_leads": internal_leads.filter(status="new").select_related("assigned_to").order_by("-created_at")[:15],
    }
    return render(request, "core/ops_dashboard.html", context)
