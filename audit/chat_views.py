"""Bounded chat feeds, explicit read receipts, and preferences."""
import uuid
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, F, Max, Q, OuterRef, Subquery
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.cache import never_cache
from .models import StaffMessage, StaffMessageParticipant, StaffNotificationPreference
from .team_views import (team_member_required, get_thread_for_user, can_post_to_thread, chat_title_for_user, team_threads_for_user,
                        create_staff_message, validate_uploaded_attachments, reaction_payload, display_user_name, attachment_url, is_updates_thread)
from .forms import StaffMessageForm


def pref_payload(user):
    pref=StaffNotificationPreference.objects.filter(user=user).first() or StaffNotificationPreference(user=user)
    return {'sound':pref.sound,'volume':pref.volume,'desktop':pref.desktop,'previews':pref.previews,'snoozed_until':pref.snoozed_until.isoformat() if pref.snoozed_until and pref.snoozed_until>timezone.now() else None}


def message_payload(request,message):
    return {'id':message.pk,'sender':display_user_name(message.sender),'sender_id':message.sender_id,'mine':message.sender_id==request.user.pk,
            'body':message.body,'created':timezone.localtime(message.created_at).strftime('%b %d, %I:%M %p'),'timestamp':message.created_at.isoformat(),
            'attachments':[{'name':a.original_filename,'size':a.size_label,'url':attachment_url(request,a.pk)} for a in message.attachments.all()],
            'reactions':reaction_payload(message,request.user)}


@team_member_required
@never_cache
@require_GET
def feed(request,pk):
    thread=get_thread_for_user(request.user,pk)
    qs=thread.messages.select_related('sender').prefetch_related('attachments','reactions__user')
    before=request.GET.get('before','')
    if before.isdigit():qs=qs.filter(pk__lt=before)
    items=list(qs.order_by('-pk')[:61]);has_more=len(items)>60;items=list(reversed(items[:60]))
    readers=list(thread.participants.filter(is_active=True,last_read_at__isnull=False).exclude(user=request.user).values('user__first_name','user__username','last_read_at'))
    return JsonResponse({'messages':[message_payload(request,m) for m in items],'has_more':has_more,'thread_updated':thread.updated_at.isoformat(),
                         'can_post':can_post_to_thread(request.user,thread),'readers':[{'name':r['user__first_name'] or r['user__username'],'at':r['last_read_at'].isoformat()} for r in readers]})


@team_member_required
@never_cache
@require_POST
def send(request,pk):
    thread=get_thread_for_user(request.user,pk)
    if not can_post_to_thread(request.user,thread):return JsonResponse({'error':'Only the owner can post announcements.'},status=403)
    form=StaffMessageForm(request.POST);files=request.FILES.getlist('attachments');file_errors=validate_uploaded_attachments(files)
    if not form.is_valid() or file_errors:return JsonResponse({'error':' '.join(file_errors) or 'Check your message.','fields':form.errors},status=400)
    body=form.cleaned_data.get('body','')
    if not body and not files:return JsonResponse({'error':'Type a message or attach a file.'},status=400)
    if len(body)>10000:return JsonResponse({'error':'Keep messages under 10,000 characters.'},status=400)
    try:nonce=uuid.UUID(request.POST.get('nonce',''))
    except ValueError:return JsonResponse({'error':'Reopen the conversation before sending.'},status=400)
    with transaction.atomic():
        # Serialize retries per sender, including those from different conversation tabs.
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        previous=StaffMessage.objects.filter(sender=request.user,client_nonce=nonce).first()
        if previous:
            if previous.thread_id!=thread.pk:return JsonResponse({'error':'This send was already used in another conversation.'},status=409)
            return JsonResponse({'message':message_payload(request,previous)})
        StaffMessageParticipant.objects.get_or_create(thread=thread,user=request.user,defaults={'last_read_at':timezone.now()})
        message=create_staff_message(thread,request.user,body,files)
        message.client_nonce=nonce;message.save(update_fields=['client_nonce'])
    return JsonResponse({'message':message_payload(request,message)},status=201)


@team_member_required
@never_cache
@require_POST
def read(request,pk):
    thread=get_thread_for_user(request.user,pk)
    value=request.POST.get('through','')
    if not value.isdigit():return JsonResponse({'error':'Choose the last displayed message.'},status=400)
    message=get_object_or_404(thread.messages,pk=value)
    StaffMessageParticipant.objects.filter(thread=thread,user=request.user,is_active=True).filter(Q(last_read_at__lt=message.created_at)|Q(last_read_at__isnull=True)).update(last_read_at=message.created_at)
    return JsonResponse({'ok':True})


@team_member_required
@never_cache
@require_POST
def read_all(request):
    StaffMessageParticipant.objects.filter(user=request.user,is_active=True).update(last_read_at=timezone.now())
    return JsonResponse({'ok':True})


@team_member_required
@never_cache
@require_POST
def mute(request,pk):
    participant=get_object_or_404(StaffMessageParticipant,thread_id=pk,user=request.user,is_active=True)
    participant.muted=request.POST.get('muted')=='true';participant.save(update_fields=['muted'])
    return JsonResponse({'muted':participant.muted})


@team_member_required
@never_cache
def preferences(request):
    if request.method=='GET':return JsonResponse(pref_payload(request.user))
    if request.method!='POST':return JsonResponse({'error':'POST required.'},status=405)
    data=request.POST
    sound=data.get('sound','aurora')
    if sound not in dict(StaffNotificationPreference._meta.get_field('sound').choices):return JsonResponse({'error':'Choose a notification sound.'},status=400)
    try:volume=int(data.get('volume',40));snooze=int(data.get('snooze',0))
    except ValueError:return JsonResponse({'error':'Choose valid notification settings.'},status=400)
    if not 0<=volume<=100 or snooze not in (-1,0,15,60,240,1440):return JsonResponse({'error':'Choose valid notification settings.'},status=400)
    pref,_=StaffNotificationPreference.objects.get_or_create(user=request.user)
    pref.sound=sound;pref.volume=volume;pref.desktop=data.get('desktop')=='true';pref.previews=data.get('previews')=='true'
    if snooze!=-1:pref.snoozed_until=timezone.now()+timedelta(minutes=snooze) if snooze else None
    pref.save();return JsonResponse(pref_payload(request.user))


@team_member_required
@never_cache
@require_GET
def summary(request):
    # Count across ALL memberships. Observer access never creates alerts or read receipts.
    own_memberships=StaffMessageParticipant.objects.filter(user=request.user,is_active=True)
    own_thread=own_memberships.filter(thread_id=OuterRef('thread_id'))
    unread=StaffMessage.objects.filter(thread_id__in=own_memberships.values('thread_id')).exclude(sender=request.user).annotate(
        own_read_at=Subquery(own_thread.values('last_read_at')[:1]), own_muted=Subquery(own_thread.values('muted')[:1])
    ).filter(Q(own_read_at__isnull=True)|Q(created_at__gt=F('own_read_at')))
    counts={r['thread_id']:r['total'] for r in unread.values('thread_id').annotate(total=Count('pk'))}
    memberships={p.thread_id:p for p in StaffMessageParticipant.objects.filter(user=request.user,is_active=True)}
    threads=list(team_threads_for_user(request.user).filter(pk__in=memberships)[:40])
    recent_ids=list(unread.filter(own_muted=False).order_by('-pk').values_list('pk',flat=True)[:12])
    alerts=[]
    for message in StaffMessage.objects.filter(pk__in=recent_ids).select_related('sender','thread').prefetch_related('thread__participants__user'):
        alerts.append({'id':message.pk,'thread_id':message.thread_id,'title':chat_title_for_user(message.thread,request.user),'body':message.body[:140],'sender':display_user_name(message.sender),'url':reverse('staff_message_thread',args=[message.thread_id])})
    last_ids = list(StaffMessage.objects.filter(thread_id__in=[t.pk for t in threads]).values('thread_id').annotate(last=Max('pk')).values_list('last',flat=True))
    last_messages = {m.thread_id:m for m in StaffMessage.objects.filter(pk__in=last_ids).select_related('sender')}
    items=[]
    for thread in threads:
        last=last_messages.get(thread.pk)
        items.append({'id':thread.pk,'title':chat_title_for_user(thread,request.user),'url':reverse('staff_message_thread',args=[thread.pk]),'unread_count':counts.get(thread.pk,0),
                      'last_message_id':last.pk if last else 0,'last_body':last.body[:140] if last else 'Start a conversation.','last_sender':display_user_name(last.sender) if last else '',
                      'updated':timezone.localtime(thread.updated_at).strftime('%b %d, %I:%M %p'),'is_group':thread.is_group,'is_updates':is_updates_thread(thread),'muted':memberships[thread.pk].muted})
    return JsonResponse({'unread_count':sum(counts.values()),'threads':items,'alerts':alerts,'preferences':pref_payload(request.user)})
