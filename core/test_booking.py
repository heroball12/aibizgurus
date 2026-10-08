from datetime import datetime, date, timedelta
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core import mail, signing
from django.test import TestCase, override_settings
from django.urls import reverse

from audit.models import EmployeeLeadEvent
from crm.models import Lead, AssessmentBooking
from crm.sales import assessment_url
from . import booking
from .booking_forms import OfficeScheduleForm
from .models import OfficeSchedule, OfficeClosure, OfficeAppointment, OfficeBookingEmail, ConsultationRequest


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', PUBLIC_BASE_URL='https://aibiz.guru')
class OfficeBookingTests(TestCase):
    def setUp(self):
        self.now = datetime(2030, 1, 6, 12, tzinfo=booking.PACIFIC)
        self.clock = patch('django.utils.timezone.now', return_value=self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.config = booking.schedule()
        self.config.enabled = True
        self.config.notification_email = 'james@aibiz.guru'
        self.config.save()
        self.owner = get_user_model().objects.create_user('office-owner', role='owner')
        self.rep = get_user_model().objects.create_user('office-rep', role='employee')
        self.day = date(2030, 1, 7)
        self.start = datetime(2030, 1, 7, 9, tzinfo=booking.PACIFIC)

    def data(self, **changes):
        return dict(action='book_in_person', date=self.day.isoformat(), starts_at=self.start.isoformat(), submission_token=signing.dumps(str(uuid4()), salt='office-submission'), name='Jordan Sample', business_name='Sample Bakery', industry='Bakery', email='jordan@example.test', phone='760-555-0100', message='Explore customer intake.', **changes)

    def post(self, data=None):
        return self.client.post(reverse('growth_assessment'), data or self.data())

    def test_format_choice_contact_and_virtual_destination(self):
        response = self.client.get(reverse('growth_assessment'))
        self.assertContains(response, '41877 Enterprise Cir, Ste 200')
        self.assertContains(response, '(760) 847-8336')
        self.assertContains(response, 'Prefer to meet in person?')
        self.assertContains(response, 'assets.calendly.com/assets/external/widget.js')
        office = self.client.get(reverse('growth_assessment'), {'mode': 'in-person'})
        self.assertContains(office, 'Meet at our Temecula office.')
        self.assertNotContains(office, 'assets.calendly.com/assets/external/widget.js')
        response = self.client.get(reverse('growth_assessment'), {'mode': 'virtual'})
        self.assertContains(response, 'https://calendly.com/james-aibiz/30min')
        self.assertContains(response, 'assets.calendly.com/assets/external/widget.js')

    def test_approved_hours_gap_weekends_and_dst(self):
        slots = booking.available_times(self.day)
        self.assertEqual([x.hour for x in slots], list(range(9, 17)))
        self.assertEqual(booking.available_times(date(2030, 1, 12)), [])
        summer = datetime(2030, 7, 7, 12, tzinfo=booking.PACIFIC)
        slots = booking.available_times(date(2030, 7, 8), now=summer)
        self.assertEqual(slots[0].utcoffset(), timedelta(hours=-7))
        self.assertEqual(slots[0].hour, 9)
        self.assertEqual(booking.available_times(self.day, now=self.start)[0].hour, 11)

    def test_confirmed_booking_crm_owner_email_customer_email_and_calendar(self):
        response = self.post()
        self.assertEqual(response.status_code, 302)
        appointment = OfficeAppointment.objects.get()
        self.assertEqual(appointment.ends_at - appointment.starts_at, timedelta(minutes=30))
        self.assertEqual(appointment.blocked_until - appointment.ends_at, timedelta(minutes=30))
        self.assertEqual(appointment.lead.status, 'appointment_scheduled')
        self.assertEqual(appointment.lead.appointment_at, self.start)
        self.assertEqual(appointment.consultation.status, 'booked_in_person')
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, ['james@aibiz.guru'])
        self.assertIn('/owner/calendar/', mail.outbox[0].body)
        self.assertEqual(mail.outbox[1].to, ['jordan@example.test'])
        self.assertTrue(mail.outbox[1].attachments)
        self.assertEqual(OfficeBookingEmail.objects.filter(delivered_at__isnull=False).count(), 2)
        event = EmployeeLeadEvent.objects.get(source='office_booking')
        self.assertTrue(event.assessment_booked)
        self.assertFalse(event.counts_as_call)
        confirmed = self.client.get(response.url)
        self.assertContains(confirmed, 'Your appointment is confirmed')
        self.assertIn('no-store', confirmed['Cache-Control'])
        self.assertEqual(confirmed['Referrer-Policy'], 'no-referrer')
        calendar = self.client.get(response.url + '?download=calendar')
        self.assertIn(b'DTSTART:20300107T170000Z', calendar.content)
        self.assertIn(b'LOCATION:41877 Enterprise Cir', calendar.content)

    def test_same_submission_is_idempotent_and_same_slot_cannot_be_rebooked(self):
        data = self.data()
        first = self.post(data)
        second = self.post(data)
        self.assertEqual(first.url, second.url)
        self.assertEqual(len(mail.outbox), 2)
        other = self.data(); other['email'] = 'other@example.test'
        response = self.post(other)
        self.assertContains(response, 'That time is no longer available')
        self.assertEqual(OfficeAppointment.objects.count(), 1)
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(ConsultationRequest.objects.count(), 1)
        self.assertEqual([x.hour for x in booking.available_times(self.day)], list(range(10, 17)))

    def test_buffer_overlap_even_after_hours_change_and_closures(self):
        self.post()
        self.config.opens_at = datetime.strptime('09:30', '%H:%M').time()
        self.config.save()
        self.assertNotIn(9, [x.hour for x in booking.available_times(self.day)])
        OfficeClosure.objects.create(starts_at=self.start + timedelta(hours=3), ends_at=self.start + timedelta(hours=4), reason='Lunch')
        self.assertNotIn(12, [x.hour for x in booking.available_times(self.day)])

    def test_scheduled_crm_and_calendly_bookings_block_office_times(self):
        Lead.objects.create(name='Virtual appointment', status='appointment_scheduled', appointment_at=self.start)
        AssessmentBooking.objects.create(invitee_uri='https://api.calendly.com/scheduled_events/test/invitees/1', event_uri='https://api.calendly.com/scheduled_events/test', starts_at=self.start + timedelta(hours=2), status='active', provider_updated_at=self.now)
        self.assertEqual([x.hour for x in booking.available_times(self.day)][:2], [10, 12])

    def test_disabled_invalid_time_expired_form_and_rate_limit(self):
        self.config.enabled = False; self.config.save()
        self.assertEqual(self.post().status_code, 200)
        self.assertFalse(OfficeAppointment.objects.exists())
        self.config.enabled = True; self.config.save()
        invalid = self.data(); invalid['starts_at'] = 'not-a-date'
        self.assertEqual(self.post(invalid).status_code, 200)
        invalid = self.data(); invalid['submission_token'] += 'tampered'
        self.assertContains(self.post(invalid), 'booking form has expired')
        with patch('core.booking_views.consume_budget', return_value=False):
            self.assertContains(self.post(), 'Too many requests')
        self.assertFalse(OfficeAppointment.objects.exists())

    def test_notification_failure_keeps_booking_and_retries_without_duplicate(self):
        with patch('core.booking.EmailMessage.send', side_effect=RuntimeError('private provider detail')):
            response = self.post()
        self.assertEqual(response.status_code, 302)
        appointment = OfficeAppointment.objects.get()
        self.assertEqual(appointment.status, 'confirmed')
        self.assertEqual(OfficeBookingEmail.objects.filter(delivered_at__isnull=True).count(), 2)
        self.assertNotIn('private provider detail', OfficeBookingEmail.objects.first().last_error)
        booking.deliver_emails(appointment.pk)
        booking.deliver_emails(appointment.pk)
        self.assertEqual(len(mail.outbox), 2)

    def test_owner_calendar_permissions_and_unread_notification(self):
        self.post()
        self.assertEqual(self.client.get(reverse('office_calendar')).status_code, 302)
        self.client.force_login(self.rep)
        self.assertEqual(self.client.get(reverse('office_calendar')).status_code, 302)
        self.client.force_login(self.owner)
        response = self.client.get(reverse('office_calendar'))
        self.assertContains(response, 'Sample Bakery')
        self.assertContains(response, 'New notification')
        self.assertContains(self.client.get(reverse('owner_dashboard')), 'Office calendar · 1 new')
        appointment = OfficeAppointment.objects.get()
        self.client.post(reverse('office_calendar'), {'action': 'seen', 'appointment': appointment.pk})
        appointment.refresh_from_db(); self.assertTrue(appointment.owner_seen)

    def test_invalid_owner_actions_return_not_found(self):
        self.client.force_login(self.owner)
        for action, field in [('cancel', 'appointment'), ('retry', 'appointment'), ('seen', 'appointment'), ('unblock', 'closure')]:
            with self.subTest(action=action):
                self.assertEqual(self.client.post(reverse('office_calendar'), {'action': action, field: 'bad-id'}).status_code, 404)

    def test_owner_cancellation_frees_slot_and_stops_stale_confirmation(self):
        with patch('core.booking_views.booking.deliver_emails'):
            self.post()
        appointment = OfficeAppointment.objects.get()
        self.client.force_login(self.owner)
        self.client.post(reverse('office_calendar'), {'action': 'cancel', 'appointment': appointment.pk})
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, 'canceled')
        self.assertIsNone(appointment.lead.appointment_at)
        self.assertEqual(len(mail.outbox), 2)
        self.assertTrue(all('canceled' in email.subject for email in mail.outbox))
        booking.deliver_emails(appointment.pk)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(booking.available_times(self.day)[0], self.start)

    def test_cancel_does_not_erase_a_newer_crm_appointment(self):
        self.post()
        appointment = OfficeAppointment.objects.get()
        Lead.objects.filter(pk=appointment.lead_id).update(appointment_at=self.start + timedelta(days=1), assessment_brief={'calendly_invitee': 'newer'})
        booking.cancel(appointment.pk)
        appointment.lead.refresh_from_db()
        self.assertEqual(appointment.lead.appointment_at, self.start + timedelta(days=1))

    def test_block_time_rejects_confirmed_visit_and_schedule_validates(self):
        self.post(); self.client.force_login(self.owner)
        response = self.client.post(reverse('office_calendar'), {'action': 'block', 'starts_at': self.start.isoformat(), 'ends_at': (self.start + timedelta(hours=1)).isoformat(), 'reason': 'Away'})
        self.assertContains(response, 'confirmed appointment in this period')
        self.assertFalse(OfficeClosure.objects.exists())
        form = OfficeScheduleForm({'enabled': True, 'notification_email': 'bad-email', 'weekdays': [0], 'opens_at': '17:00', 'closes_at': '09:00', 'duration_minutes': 30, 'buffer_minutes': 30, 'notice_hours': 2, 'horizon_days': 60})
        self.assertFalse(form.is_valid())
        self.assertIn('notification_email', form.errors)

    def test_attribution_survives_chooser_and_does_not_create_an_extra_lead(self):
        lead = Lead.objects.create(name='Jordan', email='jordan@example.test', business_name='Sample Bakery', assigned_to=self.rep)
        url = assessment_url(lead, self.rep)
        token = parse_qs(urlparse(url).query)['ref'][0]
        page = self.client.get(url + '&mode=virtual')
        self.assertContains(page, 'utm_content=')
        response = self.post(self.data(ref=token))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(OfficeAppointment.objects.get().lead_id, lead.pk)
        self.assertEqual(EmployeeLeadEvent.objects.get(source='office_booking').actor_id, self.rep.pk)

    def test_plain_followup_remains_a_request_not_a_reservation(self):
        response = self.client.post(reverse('growth_assessment'), {'name': 'Alex', 'email': 'alex@example.test', 'industry': 'Retail'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ConsultationRequest.objects.count(), 1)
        self.assertFalse(OfficeAppointment.objects.exists())
        self.assertEqual(Lead.objects.get().status, 'new')
