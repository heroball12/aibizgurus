import uuid
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from .models import StaffMessageThread, StaffMessageParticipant, StaffMessage, StaffNotificationPreference


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class TeamspaceTests(TestCase):
    def setUp(self):
        User=get_user_model()
        self.alice=User.objects.create_user(username='alice-chat',role='employee',first_name='Alice')
        self.bob=User.objects.create_user(username='bob-chat',role='employee',first_name='Bob')
        self.outsider=User.objects.create_user(username='outside-chat',role='employee')
        self.owner=User.objects.create_user(username='owner-chat',role='owner')
        self.thread=StaffMessageThread.objects.create(title='Sales team',is_group=True,created_by=self.alice)
        StaffMessageParticipant.objects.bulk_create([StaffMessageParticipant(thread=self.thread,user=u) for u in [self.alice,self.bob]])
        self.message=StaffMessage.objects.create(thread=self.thread,sender=self.bob,body='Customer asked about next week.')
        self.client.force_login(self.alice)

    def test_feed_never_marks_read_and_read_endpoint_is_monotonic(self):
        self.assertEqual(self.client.get(reverse('staff_message_feed',args=[self.thread.pk])).status_code,200)
        membership=StaffMessageParticipant.objects.get(user=self.alice,thread=self.thread)
        self.assertIsNone(membership.last_read_at)
        later=StaffMessage.objects.create(thread=self.thread,sender=self.bob,body='Another message')
        url=reverse('staff_message_read',args=[self.thread.pk])
        self.assertEqual(self.client.post(url,{'through':self.message.pk}).status_code,200)
        self.assertEqual(self.client.get(reverse('staff_message_summary')).json()['unread_count'],1)
        self.client.post(url,{'through':later.pk});self.client.post(url,{'through':self.message.pk})
        membership.refresh_from_db();self.assertEqual(membership.last_read_at,later.created_at)
        self.assertEqual(self.client.get(url).status_code,405)

    def test_unread_count_includes_older_threads_and_mute_only_silences_alerts(self):
        for i in range(45):
            thread=StaffMessageThread.objects.create(title=f'History {i}')
            StaffMessageParticipant.objects.create(thread=thread,user=self.alice)
            StaffMessage.objects.create(thread=thread,sender=self.bob,body=f'Unread {i}')
        data=self.client.get(reverse('staff_message_summary')).json()
        self.assertEqual(data['unread_count'],46);self.assertEqual(len(data['threads']),40)
        self.client.post(reverse('staff_message_mute',args=[self.thread.pk]),{'muted':'true'})
        data=self.client.get(reverse('staff_message_summary')).json()
        self.assertEqual(data['unread_count'],46)
        self.assertFalse(any(a['thread_id']==self.thread.pk for a in data['alerts']))
        self.client.post(reverse('staff_messages_read_all'))
        self.assertEqual(self.client.get(reverse('staff_message_summary')).json()['unread_count'],0)

    def test_send_is_idempotent_and_preserves_membership(self):
        url=reverse('staff_message_send',args=[self.thread.pk]);data={'body':'Next step is a Growth Assessment','nonce':str(uuid.uuid4())}
        first=self.client.post(url,data);second=self.client.post(url,data)
        self.assertEqual(first.status_code,201,first.content);self.assertEqual(second.status_code,200)
        self.assertEqual(first.json()['message']['id'],second.json()['message']['id'])
        self.assertEqual(StaffMessage.objects.filter(body=data['body']).count(),1)
        self.assertEqual(self.thread.participants.count(),2)
        for body in ['', 'x'*10001]:
            self.assertEqual(self.client.post(url,{'body':body,'nonce':str(uuid.uuid4())}).status_code,400)
        self.assertEqual(self.client.post(url,{'body':'missing nonce'}).status_code,400)
        self.assertEqual(self.client.get(url).status_code,405)

    def test_feed_has_bounded_history_and_reactions(self):
        StaffMessage.objects.bulk_create([StaffMessage(thread=self.thread,sender=self.bob,body=f'Message {i}') for i in range(125)])
        data=self.client.get(reverse('staff_message_feed',args=[self.thread.pk])).json()
        self.assertEqual(len(data['messages']),60);self.assertTrue(data['has_more'])
        first=data['messages'][0]['id']
        older=self.client.get(reverse('staff_message_feed',args=[self.thread.pk]),{'before':first}).json()
        self.assertEqual(len(older['messages']),60);self.assertLess(older['messages'][-1]['id'],first)
        self.assertEqual(self.client.post(reverse('staff_message_react',args=[self.message.pk]),{'emoji':'💜'}).status_code,200)

    def test_permissions_cover_messages_receipts_and_mutes(self):
        self.client.force_login(self.outsider)
        for route in ['staff_message_feed','staff_message_send','staff_message_read','staff_message_mute']:
            url=reverse(route,args=[self.thread.pk]);method=self.client.get if route=='staff_message_feed' else self.client.post
            self.assertEqual(method(url).status_code,404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('staff_message_feed',args=[self.thread.pk])).status_code,200)
        self.assertEqual(self.client.get(reverse('staff_message_summary')).json()['unread_count'],0)
        self.assertFalse(self.thread.participants.filter(user=self.owner).exists())

    def test_preferences_validation_persistence_isolation_and_snooze(self):
        url=reverse('staff_notification_preferences')
        payload={'sound':'glass','volume':'27','desktop':'true','previews':'false','snooze':'60'}
        response=self.client.post(url,payload);self.assertEqual(response.status_code,200)
        prefs=StaffNotificationPreference.objects.get(user=self.alice)
        self.assertEqual(prefs.sound,'glass');self.assertEqual(prefs.volume,27);self.assertFalse(prefs.previews);self.assertTrue(prefs.desktop)
        self.assertGreater(prefs.snoozed_until,timezone.now()+timedelta(minutes=59))
        self.client.post(url,{**payload,'snooze':'-1'});prefs.refresh_from_db();self.assertGreater(prefs.snoozed_until,timezone.now())
        for extra in [{'sound':'invalid'},{'volume':'101'},{'snooze':'999999'}]:self.assertEqual(self.client.post(url,{**payload,**extra}).status_code,400)
        self.client.force_login(self.bob);self.assertEqual(self.client.get(url).json()['sound'],'aurora')

    def test_client_access_csrf_and_announcement_rules(self):
        User=get_user_model();customer=User.objects.create_user(username='external',role='client')
        self.client.force_login(customer)
        self.assertEqual(self.client.get(reverse('staff_notification_preferences')).status_code,302)
        client=Client(enforce_csrf_checks=True);client.force_login(self.alice)
        self.assertEqual(client.post(reverse('staff_message_send',args=[self.thread.pk])).status_code,403)
        self.thread.title='UPDATES';self.thread.save();self.client.force_login(self.alice)
        self.assertEqual(self.client.post(reverse('staff_message_send',args=[self.thread.pk]),{'body':'not permitted','nonce':str(uuid.uuid4())}).status_code,403)

    def test_attachments_are_rejected_without_losing_retry_ability(self):
        url=reverse('staff_message_send',args=[self.thread.pk]);nonce=str(uuid.uuid4())
        response=self.client.post(url,{'body':'File','nonce':nonce,'attachments':SimpleUploadedFile('unsafe.exe',b'test')})
        self.assertEqual(response.status_code,400)
        self.assertFalse(StaffMessage.objects.filter(client_nonce=nonce).exists())
