import json
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from core.permissions import owner_required
from .calendly import CalendarError, connect, receive, verify_signature, apply_booking
from .models import CalendlyConnection, AssessmentBooking, Lead


@csrf_exempt
@require_POST
def webhook(request):
    if not settings.CALENDLY_WEBHOOK_SIGNING_KEY:
        return JsonResponse({'error':'Not configured'}, status=503)
    if len(request.body) > 256000:
        return JsonResponse({'error':'Payload too large'}, status=413)
    if not verify_signature(request.body, request.headers.get('Calendly-Webhook-Signature','')):
        return JsonResponse({'error':'Invalid signature'}, status=401)
    try:
        result = receive(json.loads(request.body))
    except CalendarError:
        return JsonResponse({'error':'Connection not configured'}, status=503)
    except (KeyError, TypeError, ValueError, AttributeError):
        return JsonResponse({'error':'Invalid payload'}, status=400)
    return JsonResponse({'status':result})


@owner_required
@never_cache
def manage(request):
    if request.method == 'POST':
        if request.POST.get('action') == 'connect':
            try:
                connect()
                messages.success(request, 'Calendly connected. New bookings, cancellations and reschedules will sync automatically.')
            except CalendarError as exc:
                messages.error(request, str(exc))
        elif request.POST.get('action') == 'match':
            if not request.POST.get('booking','').isdigit() or not request.POST.get('lead','').isdigit():
                messages.error(request, 'Enter a valid CRM lead ID.')
                return redirect('calendly_manage')
            with transaction.atomic():
                booking = get_object_or_404(AssessmentBooking.objects.select_for_update(), pk=request.POST.get('booking'))
                lead = get_object_or_404(Lead, pk=request.POST.get('lead'), lead_type='internal_sales', archived=False)
                if booking.applied_at:
                    messages.error(request, 'This booking has already been applied.')
                else:
                    booking.lead, booking.credited_to = lead, lead.assigned_to
                    booking.save(update_fields=['lead','credited_to'])
                    apply_booking(booking)
                    messages.success(request, 'Match reviewed. Check the status below.')
        return redirect('calendly_manage')
    pending = Paginator(AssessmentBooking.objects.exclude(review_reason='').select_related('lead').order_by('-received_at'), 25).get_page(request.GET.get('page'))
    return render(request, 'crm/calendly_manage.html', {'connection':CalendlyConnection.objects.filter(pk=1).first(), 'token_ready':bool(settings.CALENDLY_API_TOKEN), 'signing_ready':len(settings.CALENDLY_WEBHOOK_SIGNING_KEY)>=32, 'webhook_url':settings.PUBLIC_BASE_URL.rstrip('/')+'/crm/assessments/calendly/webhook/', 'pending':pending, 'page_obj':pending})
