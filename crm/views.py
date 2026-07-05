from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from .models import Lead
from .forms import LeadForm, LeadNoteForm

def employee_required(view):
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_employee_or_admin():
            messages.error(request, "Employee access required.")
            return redirect("portal_home")
        return view(request, *args, **kwargs)
    return wrapper

@employee_required
def crm_home(request):
    leads = Lead.objects.filter(lead_type="internal_sales")
    return render(request, "crm/crm_home.html", {"leads": leads})

@employee_required
def lead_create(request):
    if request.method == "POST":
        form = LeadForm(request.POST)
        if form.is_valid():
            lead = form.save(commit=False)
            lead.lead_type = "internal_sales"
            lead.client = None
            lead.ai_instance = None
            lead.save()
            messages.success(request, "Lead created.")
            return redirect("crm_home")
    else:
        form = LeadForm()
    return render(request, "crm/lead_form.html", {"form": form})

@employee_required
def lead_detail(request, pk):
    lead = get_object_or_404(Lead, pk=pk, lead_type="internal_sales")
    if request.method == "POST":
        form = LeadNoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.lead = lead
            note.user = request.user
            note.save()
            messages.success(request, "Note added.")
            return redirect("lead_detail", pk=lead.pk)
    else:
        form = LeadNoteForm()
    return render(request, "crm/lead_detail.html", {"lead": lead, "note_form": form})

@employee_required
def lead_edit(request, pk):
    lead = get_object_or_404(Lead, pk=pk, lead_type="internal_sales")
    if request.method == "POST":
        form = LeadForm(request.POST, instance=lead)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.lead_type = "internal_sales"
            updated.client = None
            updated.ai_instance = None
            updated.save()
            messages.success(request, "Lead updated.")
            return redirect("lead_detail", pk=lead.pk)
    else:
        form = LeadForm(instance=lead)
    return render(request, "crm/lead_form.html", {"form": form, "lead": lead})
