from datetime import timedelta
from django.db.models import Count, Q, Exists, OuterRef
from django.utils import timezone
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.urls import reverse
from urllib.parse import urlencode

from .models import Company, CompanyIntentSignal
from .views import employee_required, internal_leads_for_user, paginate, query_without_page
from .zoominfo_import import GROUPS, API_COMPANY_GROUPS, key, safe_url


@employee_required
@never_cache
def directory(request):
    visible = internal_leads_for_user(request.user)
    term = request.GET.get("q", "").strip()[:200]
    mode = "people" if request.GET.get("view") == "people" else "companies"
    intent_only = request.GET.get("intent") == "recent"
    if mode == "people":
        records = visible.exclude(name="", point_of_contact="").select_related("company", "assigned_to")
        if term:
            records = records.filter(Q(name__icontains=term) | Q(point_of_contact__icontains=term) |
                                     Q(contact_role__icontains=term) | Q(email__icontains=term) |
                                     Q(phone__icontains=term) | Q(business_name__icontains=term) |
                                     Q(company__name__icontains=term) | Q(zoominfo_profile__data__icontains=term))
        records = records.order_by("name", "point_of_contact", "pk")
    else:
        records = Company.objects.filter(people__in=visible).annotate(
            people_count=Count("people", filter=~Q(people__name="", people__point_of_contact=""), distinct=True),
            lead_count=Count("people", distinct=True),
            recent_intent=Exists(CompanyIntentSignal.objects.filter(
                zoominfo_company_id=OuterRef("zoominfo_id"), signal_date__gte=timezone.now() - timedelta(days=30))),
        ).order_by("name", "pk")
        if intent_only:
            records = records.filter(recent_intent=True)
        if term:
            records = records.filter(Q(name__icontains=term) | Q(industry__icontains=term) |
                                     Q(city__icontains=term) | Q(state__icontains=term) |
                                     Q(website__icontains=term) | Q(zoominfo_id=term))
    return render(request, "crm/companies.html", {
        "page_obj": paginate(request, records, 30), "mode": mode, "q": term, "intent_only": intent_only,
        "query_string": query_without_page(request),
        "context_sheet_url": "",
    })


@employee_required
@never_cache
def detail(request, pk):
    visible = internal_leads_for_user(request.user)
    company = get_object_or_404(Company.objects.filter(people__in=visible).distinct(), pk=pk)
    contacts = visible.filter(company=company).select_related("assigned_to").order_by("name", "point_of_contact", "pk")
    term = request.GET.get("q", "").strip()[:200]
    if term:
        contacts = contacts.filter(Q(name__icontains=term) | Q(point_of_contact__icontains=term) |
                                   Q(contact_role__icontains=term) | Q(email__icontains=term))
    sheet_query = urlencode({"source": "company", "record": company.pk, "q": term})
    source = {key(k): (k, v) for k, v in company.source_data.items()}
    groups = []
    for title, labels in GROUPS[3:] + API_COMPANY_GROUPS:
        fields = [source.pop(key(label)) for label in labels if key(label) in source]
        if fields:
            groups.append({"title": title, "fields": fields})
    return render(request, "crm/company_detail.html", {
        "company": company, "company_groups": groups, "safe_website": safe_url(company.website),
        "intent_signals": CompanyIntentSignal.objects.filter(zoominfo_company_id=company.zoominfo_id)[:8] if company.zoominfo_id else [],
        "page_obj": paginate(request, contacts, 30), "q": term,
        "query_string": query_without_page(request),
        "context_sheet_url": reverse("lead_sheet_new") + "?" + sheet_query,
        "context_export_url": reverse("lead_sheet_export") + "?" + sheet_query,
    })
