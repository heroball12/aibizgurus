"""Explicit ZoomInfo searches, credit-aware enrichment, and company Intent research."""
from datetime import timedelta

from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from audit.utils import log_activity
from core.rate_limits import consume_budget
from . import zoominfo_api as api
from .chain_detection import major_chain_name
from .importers import parse_lead_file
from .models import Company, CompanyIntentSignal, LeadUploadPreview, ZoomInfoSearch
from .views import employee_required, internal_leads_for_user, is_sales_manager, paginate, query_without_page
from .zoominfo_forms import AssignForm, SearchForm

KINDS = {"companies", "people", "intent"}


def visible_companies(user):
    return Company.objects.filter(people__in=internal_leads_for_user(user)).distinct()


def limited(request, *, enrich=False):
    scope = "zi-enrich" if enrich else "zi-search"
    return not (consume_budget(scope, request.user.pk, limit=20 if enrich else 12, window=3600 if enrich else 60)
                and consume_budget(scope + "-account", "shared", limit=50 if enrich else 40, window=3600 if enrich else 60))


def page_context(request, kind, *, form=None, run=None):
    topics = api.intent_topics() if kind == "intent" else []
    if run and kind == "intent" and not topics:
        topics = [(name, "") for name in run.criteria.get("topics", [])]
    initial = run.form_values if run else {"company_id": api.valid_id(request.GET.get("company_id"))}
    context = {"kind": kind, "form": form or SearchForm(kind=kind, topics=topics, initial=initial),
               "run": run, "configured": api.configured(), "topics_loaded": bool(topics),
               "is_manager": is_sales_manager(request.user), "assignment_form": AssignForm(user=request.user),
               "max_selection": api.MAX_SELECTION, "context_sheet_url": "",
               "recent_searches": ZoomInfoSearch.objects.filter(user=request.user).order_by("-created_at")[:6]}
    if run:
        rows = [dict(r) for r in run.results]
        ids = {r.get("company_id") for r in rows if r.get("company_id")}
        companies = {c.zoominfo_id: c.pk for c in visible_companies(request.user).filter(zoominfo_id__in=ids)}
        saved = set(CompanyIntentSignal.objects.filter(saved_by=request.user, source_key__in=[r["id"] for r in rows]).values_list("source_key", flat=True)) if kind == "intent" else set()
        for row in rows:
            row["crm_company"] = companies.get(row.get("company_id"))
            row["saved"] = row["id"] in saved
            if kind == "intent":
                row["date"] = api.signal_datetime(row.get("signal_date"))
        context.update(rows=rows, search_expired=run.created_at < timezone.now() - timedelta(hours=24),
                       next_page=run.page_number + 1, prev_page=run.page_number - 1)
    pending = request.session.get("zoominfo_error", {})
    if pending.get("kind") == kind and pending.get("run_id") == (str(run.pk) if run else ""):
        context["api_error"] = request.session.pop("zoominfo_error")["details"]
    elif run and run.error_details:
        context["api_error"] = run.error_details
    if context.get("api_error"):
        context["api_error"] = {**context["api_error"], "occurred_at": api.signal_datetime(context["api_error"].get("occurred_at"))}
    return context


def report_error(request, exc, kind, run=None):
    # Bind a redacted diagnostic to the destination, so redirects retain it without
    # showing an error from a different search tab or another employee's session.
    request.session["zoominfo_error"] = {
        "kind": kind, "run_id": str(run.pk) if run else "", "details": exc.diagnostic,
    }


@employee_required
@never_cache
@require_GET
def workspace(request):
    kind = request.GET.get("kind", "companies")
    if kind not in KINDS:
        kind = "companies"
    return render(request, "crm/zoominfo.html", page_context(request, kind))


@employee_required
@never_cache
@require_GET
def results(request, pk):
    run = get_object_or_404(ZoomInfoSearch, pk=pk, user=request.user)
    return render(request, "crm/zoominfo.html", page_context(request, run.kind, run=run))


def execute_search(request, kind, criteria, form_values, exclude, page=1):
    rows, total, has_next = api.intent_search(criteria, page) if kind == "intent" else api.search(kind, criteria, page)
    hidden = 0
    if exclude:
        filtered = [row for row in rows if not major_chain_name(name=row.get("company", ""), website=row.get("website", ""))]
        hidden, rows = len(rows) - len(filtered), filtered
    run = ZoomInfoSearch.objects.create(user=request.user, kind=kind, criteria=criteria, form_values=form_values,
                                       exclude_major_chains=exclude, results=rows, total_results=total,
                                       page_number=page, has_next=has_next, hidden_chains=hidden)
    log_activity(user=request.user, request=request, action="other", model_label="crm.ZoomInfoSearch", object_id=run.pk,
                 message=f"Searched ZoomInfo {kind}.", metadata={"results": len(rows), "page": page})
    return redirect("zoominfo_results", pk=run.pk)


@employee_required
@never_cache
@require_POST
def search(request):
    kind = request.POST.get("kind", "companies")
    if kind not in KINDS:
        return HttpResponseBadRequest("Unknown search type.")
    form = SearchForm(request.POST, kind=kind, topics=api.intent_topics() if kind == "intent" else [])
    try:
        if limited(request):
            raise api.ZoomInfoError("The CRM search limit has been reached. Please wait a minute before searching again.")
        if kind == "intent":
            form = SearchForm(request.POST, kind=kind, topics=api.intent_topics(fetch=True))
        if form.is_valid():
            return execute_search(request, kind, form.criteria(), form.snapshot(), form.cleaned_data["exclude_major_chains"])
    except api.ZoomInfoError as exc:
        report_error(request, exc, kind)
    return render(request, "crm/zoominfo.html", page_context(request, kind, form=form))


@employee_required
@never_cache
@require_POST
def change_page(request, pk):
    run = get_object_or_404(ZoomInfoSearch, pk=pk, user=request.user)
    try:
        page = int(request.POST.get("page", ""))
    except ValueError:
        return HttpResponseBadRequest("Invalid page.")
    if not ((page == run.page_number + 1 and run.has_next) or (page == run.page_number - 1 and page >= 1)):
        return HttpResponseBadRequest("Invalid page.")
    try:
        if run.created_at < timezone.now() - timedelta(hours=24):
            raise api.ZoomInfoError("This search expired. Run a new search to see current results.")
        if limited(request):
            raise api.ZoomInfoError("Please wait a minute before requesting another page.")
        return execute_search(request, run.kind, run.criteria, run.form_values, run.exclude_major_chains, page)
    except api.ZoomInfoError as exc:
        report_error(request, exc, run.kind, run)
    return redirect("zoominfo_results", pk=run.pk)


@employee_required
@never_cache
@require_POST
def load_topics(request):
    try:
        if limited(request):
            raise api.ZoomInfoError("Please wait a minute before loading topics again.")
        topics = api.intent_topics(fetch=True, fresh=True)
        messages.success(request, f"Loaded {len(topics)} ZoomInfo topics. Select the subjects relevant to your prospects.")
    except api.ZoomInfoError as exc:
        report_error(request, exc, "intent")
    # Render in this worker: the topic cache may be per process.
    return render(request, "crm/zoominfo.html", page_context(request, "intent"))


@employee_required
@never_cache
@require_POST
def test_connection(request):
    if not is_sales_manager(request.user):
        return HttpResponseBadRequest("Manager access required.")
    try:
        if limited(request):
            raise api.ZoomInfoError("Please wait a minute before checking the connection again.")
        api.token(refresh=True)
        fields = api.output_fields(fresh=True)
        messages.success(request, f"ZoomInfo authentication and contact field lookup succeeded ({len(fields)} fields listed). No contact details were purchased. Search, enrichment, and Intent access are checked separately when used.")
    except api.ZoomInfoError as exc:
        report_error(request, exc, "companies")
    return redirect("zoominfo_workspace")


def enrichment_preview(request, run):
    """Create/reopen a local preview from received data, never another provider call."""
    with transaction.atomic():
        run = ZoomInfoSearch.objects.select_for_update().get(pk=run.pk, user=request.user)
        if run.preview and (run.preview.confirmed_import_id or run.preview.created_at >= timezone.now() - timedelta(minutes=30)):
            return redirect("lead_import_preview", pk=run.preview_id)
        chosen = [r for r in run.results if r["id"] in run.selected_ids]
        content, skipped = api.preview_csv(run.enrichment, chosen)
        if not content:
            run.state = "empty"
            run.error = "ZoomInfo returned no unambiguous full contact matches. No CRM records were changed. Review usage in ZoomInfo before requesting new details."
            run.save(update_fields=["state", "error", "updated_at"])
            messages.warning(request, run.error)
            return redirect("zoominfo_results", pk=run.pk)
        upload = SimpleUploadedFile("zoominfo-api-contacts.csv", content)
        parsed = parse_lead_file(upload, default_assigned_to=run.assigned_to,
                                 force_assigned_to=None if is_sales_manager(request.user) else request.user)
        if parsed.errors:
            raise api.ZoomInfoError("ZoomInfo details were received, but could not be prepared for import. The response is saved; reopening the preview will not request paid details again.")
        draft = LeadUploadPreview.objects.create(uploaded_by=request.user, original_filename=upload.name, content=content, assigned_to=run.assigned_to)
        run.preview = draft
        run.save(update_fields=["preview", "updated_at"])
    if skipped:
        messages.warning(request, f"Excluded {skipped} non-matching or ambiguous responses. Review the full matches below.")
    return redirect("lead_import_preview", pk=draft.pk)


@employee_required
@never_cache
@require_POST
def get_details(request, pk):
    run = get_object_or_404(ZoomInfoSearch, pk=pk, user=request.user, kind="people")
    try:
        if run.state == "complete":
            return enrichment_preview(request, run)
        if run.state != "ready":
            raise api.ZoomInfoError("This request is already in progress or its outcome needs checking. Paid details will not be requested again. Check ZoomInfo usage before starting a new search.")
        if run.created_at < timezone.now() - timedelta(hours=24):
            raise api.ZoomInfoError("This search expired. Search again before retrieving contact details.")
        ids = list(dict.fromkeys(request.POST.getlist("selected")))
        permitted = {r["id"] for r in run.results}
        if not 1 <= len(ids) <= api.MAX_SELECTION or not set(ids) <= permitted:
            raise api.ZoomInfoError(f"Select between 1 and {api.MAX_SELECTION} people from these results.")
        assignment = AssignForm(request.POST, user=request.user)
        if not assignment.is_valid():
            raise api.ZoomInfoError("Choose an active employee for assignment.")
        if limited(request, enrich=True):
            raise api.ZoomInfoError("The CRM's contact-detail request limit has been reached. Please try again in an hour.")
        fields = api.output_fields()
        # Reserve before the chargeable request, outside the network transaction.
        with transaction.atomic():
            locked = ZoomInfoSearch.objects.select_for_update().get(pk=run.pk, user=request.user)
            if locked.state != "ready":
                raise api.ZoomInfoError("Details were already requested for this search. Reload to see the status.")
            locked.state, locked.selected_ids, locked.assigned_to = "enriching", ids, assignment.assignee()
            locked.error = ""
            locked.error_details = {}
            locked.save(update_fields=["state", "selected_ids", "assigned_to", "error", "error_details", "updated_at"])
        try:
            payload = api.enrich(ids, fields)
        except api.ZoomInfoError as exc:
            ZoomInfoSearch.objects.filter(pk=run.pk).update(state="uncertain" if exc.uncertain else "ready", error=str(exc)[:500], error_details=exc.diagnostic, updated_at=timezone.now())
            raise
        # Keep the response before parsing so malformed/partial data cannot trigger recharges.
        ZoomInfoSearch.objects.filter(pk=run.pk).update(state="complete", enrichment=payload, error="", error_details={}, updated_at=timezone.now())
        run.refresh_from_db()
        log_activity(user=request.user, request=request, action="other", model_label="crm.ZoomInfoSearch", object_id=run.pk,
                     message="Retrieved ZoomInfo contact details for import review.", metadata={"selected": len(ids)})
        return enrichment_preview(request, run)
    except api.ZoomInfoError as exc:
        report_error(request, exc, run.kind, run)
    return redirect("zoominfo_results", pk=run.pk)


@employee_required
@never_cache
@require_POST
def save_signal(request, pk):
    run = get_object_or_404(ZoomInfoSearch, pk=pk, user=request.user, kind="intent")
    row = next((r for r in run.results if r["id"] == request.POST.get("signal")), None)
    if not row or not row.get("saveable"):
        return HttpResponseBadRequest("This signal is missing verified company, date or score fields.")
    with transaction.atomic():
        signal, created = CompanyIntentSignal.objects.get_or_create(source_key=row["id"], defaults={
            "provider_id": row["provider_id"], "zoominfo_company_id": row["company_id"],
            "company_name": row["company"], "website": row["website"], "topic": row["topic"], "category": row["category"],
            "signal_date": api.signal_datetime(row["signal_date"]), "score": row["score"],
            "audience_strength": row["audience_strength"], "raw": row["raw"],
        })
        signal.saved_by.add(request.user)
    log_activity(user=request.user, request=request, action="other", model_label="crm.CompanyIntentSignal", object_id=signal.pk,
                 message="Saved a ZoomInfo company Intent signal.", metadata={"new_signal": created})
    messages.success(request, "Signal saved. It appears on the matching ZoomInfo company profile when that company is in your CRM. No sales activity or call was recorded.")
    return redirect("zoominfo_results", pk=run.pk)


@employee_required
@never_cache
@require_GET
def saved_signals(request):
    companies = visible_companies(request.user)
    signals = CompanyIntentSignal.objects.all()
    if not is_sales_manager(request.user):
        signals = signals.filter(Q(saved_by=request.user) | Q(zoominfo_company_id__in=companies.exclude(zoominfo_id=None).values("zoominfo_id"))).distinct()
    term = request.GET.get("q", "").strip()[:200]
    if term:
        signals = signals.filter(Q(company_name__icontains=term) | Q(topic__icontains=term) | Q(category__icontains=term))
    days = request.GET.get("days", "30")
    if days not in {"7", "14", "30", "90", "all"}:
        days = "30"
    if days != "all":
        signals = signals.filter(signal_date__gte=timezone.now() - timedelta(days=int(days)))
    score = request.GET.get("score", "")
    if score in {"70", "80", "90"}:
        signals = signals.filter(score__gte=int(score))
    else:
        score = ""
    company_id = api.valid_id(request.GET.get("company_id"))
    if company_id:
        signals = signals.filter(zoominfo_company_id=company_id)
    page = paginate(request, signals, 25)
    company_map = {c.zoominfo_id: c.pk for c in companies.filter(zoominfo_id__in=[s.zoominfo_company_id for s in page])}
    for signal in page:
        signal.crm_company = company_map.get(signal.zoominfo_company_id)
    return render(request, "crm/intent_signals.html", {"page_obj": page, "q": term, "days": days, "score": score,
                   "company_id": company_id, "query_string": query_without_page(request), "context_sheet_url": ""})
