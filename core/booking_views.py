import calendar
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from uuid import uuid4

from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from crm.models import Lead
from crm.sales import BOOKING_URL
from . import booking
from .booking_forms import OfficeBookingForm, OfficeClosureForm, OfficeScheduleForm
from .booking_models import OfficeAppointment, OfficeBookingEmail, OfficeClosure, OfficeSchedule
from .forms import ConsultationRequestForm
from .permissions import owner_required
from .rate_limits import consume_budget, request_identity


def _day(value, default):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return default


def _posted_object(model, value):
    try:
        return get_object_or_404(model, pk=value)
    except (ValueError, TypeError, ValidationError):
        raise Http404 from None


@never_cache
@require_http_methods(["GET", "POST"])
def assessment(request):
    config = booking.schedule()
    today = timezone.now().astimezone(booking.PACIFIC).date()
    last_day = today + timedelta(days=config.horizon_days)
    selected_day = _day(request.POST.get("date") or request.GET.get("date"), today)
    selected_day = min(max(selected_day, today), last_day)
    mode = "in-person" if request.GET.get("mode") == "in-person" else "virtual"
    demo_ref = (request.POST.get("demo_ref") or request.GET.get("demo_ref", ""))[:2000]
    ref = (request.POST.get("ref") or request.GET.get("ref", ""))[:2000]
    if ref:
        try:
            signing.loads(ref, salt="assessment-attribution", max_age=180 * 86400)
        except signing.BadSignature:
            ref = ""
    form = ConsultationRequestForm()
    office_form = OfficeBookingForm(initial={"submission_token": signing.dumps(str(uuid4()), salt="office-submission")})
    if request.method == "POST":
        allowed = consume_budget("consultation", request_identity(request), limit=5, window=3600)
        if request.POST.get("action") == "book_in_person":
            mode = "in-person"
            office_form = OfficeBookingForm(request.POST)
            valid = office_form.is_valid()
            if not allowed:
                office_form.add_error(None, "Too many requests. Please call us or try again later.")
            elif valid:
                try:
                    appointment = booking.reserve(request, office_form.cleaned_data)
                except (booking.BookingError, IntegrityError) as exc:
                    office_form.add_error(None, str(exc) if isinstance(exc, booking.BookingError) else "That time was just reserved. Choose another time.")
                else:
                    booking.deliver_emails(appointment.pk)
                    return redirect("office_confirmation", token=booking.confirmation_token(appointment))
        else:
            form = ConsultationRequestForm(request.POST)
            valid = form.is_valid()
            if not allowed:
                form.add_error(None, "Too many requests. Please try again later or call us.")
            elif valid:
                with transaction.atomic():
                    obj = form.save()
                    lead = Lead.objects.create(lead_type="internal_sales", name=obj.name, business_name=obj.business_name, phone=obj.phone, email=obj.email, industry=obj.industry, source="AI Business Growth Assessment", status="new", notes=obj.message)
                    from .experience.access import attribute_assessment
                    attribute_assessment(request, obj, lead)
                messages.success(request, "Assessment request received. We will review your growth opportunities and follow up shortly.")
                return redirect("growth_assessment")
    # Default to the first bookable day; an explicit date selection stays selected.
    if mode == "in-person" and "date" not in request.GET and "date" not in request.POST and config.enabled:
        while selected_day < last_day and not booking.available_times(selected_day, config):
            selected_day += timedelta(days=1)
    params = {key: value for key, value in {"demo_ref": demo_ref, "ref": ref}.items() if value}
    virtual_url = reverse("growth_assessment") + "?" + urlencode({**params, "mode": "virtual"})
    office_url = reverse("growth_assessment") + "?" + urlencode({**params, "mode": "in-person"})
    virtual_booking = BOOKING_URL + ("?" + urlencode({"utm_source": "aibiz-crm", "utm_medium": "sales", "utm_content": ref}) if ref else "")
    slots = booking.available_times(selected_day, config) if mode == "in-person" else []
    context = {"form": form, "office_form": office_form, "mode": mode, "schedule": config, "slots": slots, "selected_day": selected_day, "today": today, "last_day": last_day, "demo_ref": demo_ref, "ref": ref, "virtual_url": virtual_url, "office_url": office_url, "booking_url": virtual_booking, "widget_url": virtual_booking + ("&" if ref else "?") + "hide_gdpr_banner=1&primary_color=7c3aed", "office_fields": [field for field in office_form if field.name not in {"starts_at", "submission_token", "website_confirm"}]}
    return render(request, "core/growth_assessment.html", context)


@never_cache
@require_http_methods(["GET"])
def confirmation(request, token):
    try:
        pk = signing.loads(token, salt="office-confirmation", max_age=180 * 86400)
        appointment = OfficeAppointment.objects.get(pk=pk)
    except (signing.BadSignature, OfficeAppointment.DoesNotExist, ValueError):
        raise Http404 from None
    if request.GET.get("download") == "calendar":
        response = HttpResponse(booking.ics(appointment), content_type="text/calendar; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="growth-assessment.ics"'
    else:
        response = render(request, "core/office_confirmation.html", {"appointment": appointment, "email_sent": appointment.emails.filter(kind=f"{appointment.status}_visitor", delivered_at__isnull=False).exists()})
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@owner_required
@never_cache
@require_http_methods(["GET", "POST"])
def owner_calendar(request):
    config = booking.schedule()
    settings_form = OfficeScheduleForm(instance=config)
    closure_form = OfficeClosureForm()
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "settings":
            with transaction.atomic():
                config = OfficeSchedule.objects.select_for_update().get(pk=1)
                settings_form = OfficeScheduleForm(request.POST, instance=config)
                if settings_form.is_valid():
                    settings_form.save()
                    messages.success(request, "Office availability updated. Existing appointments keep their original time and gap.")
                    return redirect("office_calendar")
        elif action == "block":
            closure_form = OfficeClosureForm(request.POST)
            if closure_form.is_valid():
                with transaction.atomic():
                    OfficeSchedule.objects.select_for_update().get(pk=1)
                    start, end = closure_form.cleaned_data["starts_at"], closure_form.cleaned_data["ends_at"]
                    if OfficeAppointment.objects.filter(status="confirmed", starts_at__lt=end, blocked_until__gt=start).exists():
                        closure_form.add_error(None, "There is a confirmed appointment in this period. Cancel or arrange a new time with that customer first.")
                    else:
                        closure_form.save()
                        messages.success(request, "Time blocked. Customers cannot book this period.")
                        return redirect("office_calendar")
        elif action == "unblock":
            with transaction.atomic():
                OfficeSchedule.objects.select_for_update().get(pk=1)
                _posted_object(OfficeClosure, request.POST.get("closure")).delete()
            messages.success(request, "Time block removed.")
            return redirect("office_calendar")
        elif action in {"cancel", "retry", "seen"}:
            appointment = _posted_object(OfficeAppointment, request.POST.get("appointment"))
            if action == "cancel":
                booking.cancel(appointment.pk)
                booking.deliver_emails(appointment.pk)
                messages.success(request, "Appointment canceled. Its office time is available again; notification status is shown below.")
            elif action == "retry":
                booking.deliver_emails(appointment.pk, limit=4)
                messages.info(request, "Delivery retried. Check the notification status below.")
            else:
                OfficeAppointment.objects.filter(pk=appointment.pk).update(owner_seen=True)
            return redirect("office_calendar")
    today = timezone.now().astimezone(booking.PACIFIC).date()
    month = _day(request.GET.get("month", "") + "-01", today.replace(day=1))
    if abs((month - today).days) > 730:
        month = today.replace(day=1)
    dates = list(calendar.Calendar().itermonthdates(month.year, month.month))
    start = datetime.combine(dates[0], datetime.min.time(), booking.PACIFIC)
    end = datetime.combine(dates[-1] + timedelta(days=1), datetime.min.time(), booking.PACIFIC)
    appointments = list(OfficeAppointment.objects.filter(starts_at__gte=start, starts_at__lt=end).select_related("lead").prefetch_related("emails"))
    by_day = {}
    for appointment in appointments:
        by_day.setdefault(appointment.starts_at.astimezone(booking.PACIFIC).date(), []).append(appointment)
        appointment.notifications = [item for item in appointment.emails.all() if item.kind.startswith(appointment.status)]
    cells = [{"date": day, "current": day.month == month.month, "today": day == today, "appointments": by_day.get(day, [])} for day in dates]
    external = Lead.objects.filter(lead_type="internal_sales", status="appointment_scheduled", appointment_at__gte=start, appointment_at__lt=end).exclude(pk__in=[item.lead_id for item in appointments]).order_by("appointment_at")
    return render(request, "core/office_calendar.html", {"settings_form": settings_form, "closure_form": closure_form, "schedule": config, "month": month, "previous_month": (month.replace(day=1) - timedelta(days=1)).strftime("%Y-%m"), "next_month": (month.replace(day=28) + timedelta(days=4)).strftime("%Y-%m"), "cells": cells, "appointments": appointments, "external": external, "closures": OfficeClosure.objects.filter(ends_at__gte=timezone.now())[:100], "mail_ready": booking.email_ready()})
