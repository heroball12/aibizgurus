from datetime import timedelta
from pathlib import Path

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import StaffMessageForm, StaffMessageThreadForm, TimeClockEntryForm, TimeClockNoteForm
from .models import (
    StaffMessage,
    StaffMessageAttachment,
    StaffMessageParticipant,
    StaffMessageReaction,
    StaffMessageThread,
    TimeClockEntry,
)
from .utils import get_client_ip, log_activity


User = get_user_model()
UPDATES_THREAD_TITLE = "UPDATES"
REACTION_EMOJIS = ["👍", "❤️", "😂", "🎉", "🔥", "✅", "👀", "💜", "🚀"]
ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".rtf",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ppt", ".pptx", ".zip",
}
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 6
AUTO_CLOCK_OUT_AFTER = timedelta(hours=8)


def team_member_required(view_func):
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_employee_or_admin():
            messages.error(request, "Staff access required.")
            return redirect("portal_home")
        return view_func(request, *args, **kwargs)
    return wrapper


def can_view_all_staff_messages(user):
    return user.is_authenticated and user.is_owner()


def can_manage_time_clock(user):
    return user.is_authenticated and (user.is_owner() or getattr(user, "role", "") == "admin")


def active_internal_staff_queryset():
    return (
        User.objects
        .filter(Q(role__in=["employee", "admin", "owner"]) | Q(is_staff=True) | Q(is_superuser=True), is_active=True)
        .distinct()
        .order_by("first_name", "username")
    )


def display_user_name(user):
    if not user:
        return "System"
    return user.get_full_name() or user.first_name or user.username


def first_name_for(user):
    if not user:
        return "System"
    return user.first_name or (user.get_full_name().split(" ", 1)[0] if user.get_full_name() else "") or user.username


def is_updates_thread(thread):
    return (thread.title or "").strip().upper() == UPDATES_THREAD_TITLE


def ensure_updates_thread():
    thread = StaffMessageThread.objects.filter(title__iexact=UPDATES_THREAD_TITLE).order_by("pk").first()
    if thread is None:
        thread = StaffMessageThread.objects.create(title=UPDATES_THREAD_TITLE, is_group=True)
    elif thread.title != UPDATES_THREAD_TITLE or not thread.is_group:
        thread.title = UPDATES_THREAD_TITLE
        thread.is_group = True
        thread.save(update_fields=["title", "is_group"])

    staff_users = list(active_internal_staff_queryset())
    existing_participants = {
        participant.user_id: participant
        for participant in StaffMessageParticipant.objects.filter(thread=thread, user__in=staff_users)
    }
    inactive_ids = []
    new_participants = []
    for staff_user in staff_users:
        participant = existing_participants.get(staff_user.pk)
        if participant is None:
            new_participants.append(StaffMessageParticipant(thread=thread, user=staff_user))
        elif not participant.is_active:
            inactive_ids.append(participant.pk)
    if new_participants:
        StaffMessageParticipant.objects.bulk_create(new_participants, ignore_conflicts=True)
    if inactive_ids:
        StaffMessageParticipant.objects.filter(pk__in=inactive_ids).update(is_active=True)
    return thread


def chat_title_for_user(thread, user):
    if is_updates_thread(thread):
        return UPDATES_THREAD_TITLE

    prefetched = getattr(thread, "_prefetched_objects_cache", {}).get("participants")
    participants = list(prefetched) if prefetched is not None else list(thread.participants.select_related("user").all())
    active_users = [participant.user for participant in participants if participant.is_active]
    if user and user.is_authenticated and not thread.is_group:
        other_users = [participant_user for participant_user in active_users if participant_user.pk != user.pk]
        if len(other_users) == 1:
            return display_user_name(other_users[0])
        if other_users:
            return ", ".join(display_user_name(participant_user) for participant_user in other_users)
    if thread.title:
        return thread.title
    if active_users:
        return ", ".join(display_user_name(participant_user) for participant_user in active_users)
    return f"Chat #{thread.pk}"


def decorate_chat_titles(threads, user):
    for thread in threads:
        thread.chat_title = chat_title_for_user(thread, user)
    return threads


def can_post_to_thread(user, thread):
    if is_updates_thread(thread):
        return user.is_authenticated and user.is_owner()
    return True


def reaction_payload(message, user):
    counts = {}
    mine = set()
    for reaction in message.reactions.all():
        counts[reaction.emoji] = counts.get(reaction.emoji, 0) + 1
        if user.is_authenticated and reaction.user_id == user.pk:
            mine.add(reaction.emoji)
    return [
        {"emoji": emoji, "count": counts[emoji], "mine": emoji in mine}
        for emoji in REACTION_EMOJIS
        if counts.get(emoji)
    ]


def announce_time_clock_event(employee, event, note="", actor=None):
    employee_name = first_name_for(employee)
    note_text = f" Note: {note.strip()}" if note and note.strip() else ""
    if event == "clock_in":
        body = f"{employee_name} clocked in.{note_text}"
    elif event == "clock_out":
        body = f"{employee_name} clocked out.{note_text}"
    elif event == "auto_clock_out":
        body = f"{employee_name} was automatically clocked out after 8 hours.{note_text}"
    elif event == "admin_clock_out":
        actor_name = display_user_name(actor) if actor else "Admin"
        body = f"{employee_name} was clocked out by {actor_name}.{note_text}"
    else:
        body = f"{employee_name} time clock update.{note_text}"
    thread = ensure_updates_thread()
    return create_staff_message(thread, employee, body, [])


def auto_clock_out_overdue_entries(request=None):
    now = timezone.now()
    cutoff = now - AUTO_CLOCK_OUT_AFTER
    overdue_entries = list(
        TimeClockEntry.objects
        .filter(clock_out__isnull=True, clock_in__lte=cutoff)
        .select_related("employee")
    )
    for entry in overdue_entries:
        entry.clock_out = entry.clock_in + AUTO_CLOCK_OUT_AFTER
        auto_note = "Auto clock-out after 8 hours."
        entry.note = f"{entry.note} · {auto_note}" if entry.note and auto_note not in entry.note else (entry.note or auto_note)
        entry.save(update_fields=["clock_out", "note", "updated_at"])
        announce_time_clock_event(entry.employee, "auto_clock_out", note=auto_note)
        log_activity(
            user=getattr(request, "user", None) if request else None,
            request=request,
            action="update",
            model_label="audit.TimeClockEntry",
            object_id=entry.pk,
            object_repr=str(entry),
            message=f"Auto clocked out {entry.employee} after 8 hours.",
        )
    return len(overdue_entries)


def team_threads_for_user(user):
    queryset = StaffMessageThread.objects.prefetch_related("participants__user").annotate(
        message_count=Count("messages", distinct=True),
        last_message_at=Max("messages__created_at"),
    )
    if can_view_all_staff_messages(user):
        return queryset.order_by("-updated_at", "-created_at")
    return queryset.filter(participants__user=user, participants__is_active=True).distinct().order_by("-updated_at", "-created_at")


def get_thread_for_user(user, pk):
    return get_object_or_404(team_threads_for_user(user), pk=pk)


def thread_unread_count(thread, user):
    participant = next(
        (
            item for item in getattr(thread, "_prefetched_objects_cache", {}).get("participants", [])
            if item.user_id == user.pk and item.is_active
        ),
        None,
    )
    if participant is None:
        participant = StaffMessageParticipant.objects.filter(thread=thread, user=user, is_active=True).first()
    if participant is None:
        return 0
    unread = thread.messages.exclude(sender=user)
    if participant.last_read_at:
        unread = unread.filter(created_at__gt=participant.last_read_at)
    return unread.count()


def mark_thread_read(thread, user):
    StaffMessageParticipant.objects.filter(thread=thread, user=user, is_active=True).update(last_read_at=timezone.now())


def paginate(request, queryset, per_page=25):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def validate_uploaded_attachments(files):
    errors = []
    if len(files) > MAX_ATTACHMENTS_PER_MESSAGE:
        errors.append(f"Attach up to {MAX_ATTACHMENTS_PER_MESSAGE} files per message.")
    for uploaded in files:
        name = Path(uploaded.name or "").name
        extension = Path(name).suffix.lower()
        if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
            errors.append(f"{name or 'Attachment'} is not an allowed file type.")
        if uploaded.size > MAX_ATTACHMENT_BYTES:
            errors.append(f"{name or 'Attachment'} is too large. Max size is 15 MB.")
    return errors


def create_staff_message(thread, sender, body, files):
    message = StaffMessage.objects.create(
        thread=thread,
        sender=sender,
        body=body or ("📎 Sent attachment" if files else ""),
    )
    for uploaded in files:
        StaffMessageAttachment.objects.create(
            message=message,
            file=uploaded,
            original_filename=Path(uploaded.name or "attachment").name[:255],
            content_type=(getattr(uploaded, "content_type", "") or "")[:120],
            size=uploaded.size or 0,
            uploaded_by=sender,
        )
    thread.save(update_fields=["updated_at"])
    return message


@team_member_required
def staff_messages(request):
    ensure_updates_thread()
    threads = team_threads_for_user(request.user)
    page_obj = paginate(request, threads, 30)
    decorate_chat_titles(page_obj.object_list, request.user)
    return render(request, "audit/staff_messages.html", {
        "page_obj": page_obj,
        "can_view_all": can_view_all_staff_messages(request.user),
    })


@team_member_required
def staff_message_create(request):
    ensure_updates_thread()
    if request.method == "POST":
        form = StaffMessageThreadForm(request.POST, user=request.user)
        files = request.FILES.getlist("attachments")
        file_errors = validate_uploaded_attachments(files)
        if form.is_valid() and not file_errors:
            if not form.cleaned_data.get("message") and not files:
                form.add_error("message", "Type a message or attach a file.")
            else:
                selected = list(form.cleaned_data["participants"])
                participants = {user.pk: user for user in selected}
                participants[request.user.pk] = request.user
                title = form.cleaned_data.get("title", "").strip()
                thread = StaffMessageThread.objects.create(
                    title=title,
                    is_group=len(participants) > 2,
                    created_by=request.user,
                )
                now = timezone.now()
                StaffMessageParticipant.objects.bulk_create([
                    StaffMessageParticipant(
                        thread=thread,
                        user=user,
                        last_read_at=now if user.pk == request.user.pk else None,
                    )
                    for user in participants.values()
                ])
                create_staff_message(thread, request.user, form.cleaned_data["message"], files)
                mark_thread_read(thread, request.user)
                log_activity(
                    user=request.user,
                    request=request,
                    action="create",
                    model_label="audit.StaffMessageThread",
                    object_id=thread.pk,
                    object_repr=chat_title_for_user(thread, request.user),
                    message="Created internal staff chat thread.",
                )
                messages.success(request, "Chat thread created.")
                return redirect("staff_message_thread", pk=thread.pk)
        for error in file_errors:
            form.add_error(None, error)
    else:
        form = StaffMessageThreadForm(user=request.user)
    return render(request, "audit/staff_message_form.html", {"form": form})


@team_member_required
def staff_message_thread(request, pk):
    ensure_updates_thread()
    thread = get_thread_for_user(request.user, pk)
    form = StaffMessageForm()
    if request.method == "POST":
        form = StaffMessageForm(request.POST)
        files = request.FILES.getlist("attachments")
        file_errors = validate_uploaded_attachments(files)
        if not can_post_to_thread(request.user, thread):
            form.add_error(None, "Only the owner can post in UPDATES. Everyone else can read and react.")
        elif form.is_valid() and not file_errors:
            if not form.cleaned_data.get("body") and not files:
                form.add_error("body", "Type a message or attach a file.")
            else:
                StaffMessageParticipant.objects.get_or_create(thread=thread, user=request.user)
                create_staff_message(thread, request.user, form.cleaned_data["body"], files)
                mark_thread_read(thread, request.user)
                log_activity(
                    user=request.user,
                    request=request,
                    action="create",
                    model_label="audit.StaffMessage",
                    object_id=thread.pk,
                    object_repr=chat_title_for_user(thread, request.user),
                    message="Sent internal staff chat message.",
                )
                return redirect("staff_message_thread", pk=thread.pk)
        for error in file_errors:
            form.add_error(None, error)
    messages_qs = thread.messages.select_related("sender").prefetch_related("attachments", "reactions__user").order_by("created_at")
    sidebar_threads = list(team_threads_for_user(request.user)[:40])
    decorate_chat_titles(sidebar_threads, request.user)
    chat_title = chat_title_for_user(thread, request.user)
    mark_thread_read(thread, request.user)
    return render(request, "audit/staff_message_thread.html", {
        "thread": thread,
        "chat_title": chat_title,
        "thread_messages": messages_qs,
        "sidebar_threads": sidebar_threads,
        "form": form,
        "reaction_emojis": REACTION_EMOJIS,
        "can_post": can_post_to_thread(request.user, thread),
        "is_updates": is_updates_thread(thread),
        "can_view_all": can_view_all_staff_messages(request.user),
        "is_observer": (
            can_view_all_staff_messages(request.user)
            and not is_updates_thread(thread)
            and not thread.participants.filter(user=request.user).exists()
        ),
    })


@team_member_required
def staff_message_feed(request, pk):
    thread = get_thread_for_user(request.user, pk)
    mark_thread_read(thread, request.user)
    items = []
    for message in thread.messages.select_related("sender").prefetch_related("attachments", "reactions__user").order_by("created_at"):
        sender = message.sender
        items.append({
            "id": message.pk,
            "sender": sender.get_full_name() or sender.username if sender else "System",
            "sender_id": sender.pk if sender else None,
            "mine": sender == request.user,
            "body": message.body,
            "created": timezone.localtime(message.created_at).strftime("%b %-d, %Y %-I:%M %p"),
            "attachments": [
                {
                    "name": attachment.original_filename,
                    "size": attachment.size_label,
                    "url": attachment_url(request, attachment.pk),
                }
                for attachment in message.attachments.all()
            ],
            "reactions": reaction_payload(message, request.user),
        })
    return JsonResponse({
        "messages": items,
        "thread_updated": thread.updated_at.isoformat(),
        "can_post": can_post_to_thread(request.user, thread),
    })


@team_member_required
def staff_message_react(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    message = get_object_or_404(
        StaffMessage.objects.select_related("thread", "sender").prefetch_related("reactions__user"),
        pk=pk,
    )
    get_thread_for_user(request.user, message.thread_id)
    emoji = (request.POST.get("emoji") or "").strip()
    if emoji not in REACTION_EMOJIS:
        return JsonResponse({"error": "Unsupported reaction."}, status=400)
    reaction, created = StaffMessageReaction.objects.get_or_create(
        message=message,
        user=request.user,
        emoji=emoji,
    )
    toggled_on = created
    if not created:
        reaction.delete()
        toggled_on = False
    message.thread.save(update_fields=["updated_at"])
    refreshed_message = (
        StaffMessage.objects
        .select_related("thread", "sender")
        .prefetch_related("reactions__user")
        .get(pk=message.pk)
    )
    return JsonResponse({
        "message_id": refreshed_message.pk,
        "reactions": reaction_payload(refreshed_message, request.user),
        "toggled_on": toggled_on,
    })


@team_member_required
def staff_message_summary(request):
    ensure_updates_thread()
    threads = list(team_threads_for_user(request.user)[:8])
    decorate_chat_titles(threads, request.user)
    total_unread = 0
    items = []
    for thread in threads:
        unread_count = thread_unread_count(thread, request.user)
        total_unread += unread_count
        last_message = thread.messages.select_related("sender").order_by("-created_at").first()
        sender = last_message.sender if last_message else None
        sender_name = sender.get_full_name() or sender.username if sender else "System"
        items.append({
            "id": thread.pk,
            "title": thread.chat_title,
            "participants": thread.participant_names(),
            "url": request.build_absolute_uri(reverse("staff_message_thread", args=[thread.pk])),
            "unread_count": unread_count,
            "updated": timezone.localtime(thread.updated_at).strftime("%b %-d, %-I:%M %p"),
            "last_sender": sender_name,
            "last_body": last_message.body[:140] if last_message else "No chat yet.",
            "is_group": thread.is_group,
            "is_updates": is_updates_thread(thread),
        })
    return JsonResponse({
        "unread_count": total_unread,
        "threads": items,
        "messages_url": request.build_absolute_uri(reverse("staff_messages")),
        "new_message_url": request.build_absolute_uri(reverse("staff_message_create")),
    })


def attachment_url(request, attachment_id):
    from django.urls import reverse

    return request.build_absolute_uri(reverse("staff_message_attachment", args=[attachment_id]))


@team_member_required
def staff_message_attachment(request, pk):
    attachment = get_object_or_404(
        StaffMessageAttachment.objects.select_related("message__thread"),
        pk=pk,
    )
    get_thread_for_user(request.user, attachment.message.thread_id)
    if not attachment.file:
        raise Http404("Attachment file not found.")
    try:
        file_handle = attachment.file.open("rb")
    except OSError as exc:
        raise Http404("Attachment file not found.") from exc
    return FileResponse(
        file_handle,
        as_attachment=True,
        filename=attachment.original_filename,
        content_type=attachment.content_type or "application/octet-stream",
    )


@team_member_required
def staff_time_clock(request):
    auto_clock_out_overdue_entries(request)
    open_entry = TimeClockEntry.objects.filter(employee=request.user, clock_out__isnull=True).order_by("-clock_in").first()
    form = TimeClockNoteForm(request.POST or None)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "clock_in":
            if open_entry:
                messages.info(request, "You are already clocked in.")
            elif form.is_valid():
                open_entry = TimeClockEntry.objects.create(
                    employee=request.user,
                    note=form.cleaned_data.get("note", ""),
                    clock_in_ip=get_client_ip(request),
                )
                announce_time_clock_event(request.user, "clock_in", note=open_entry.note)
                log_activity(
                    user=request.user,
                    request=request,
                    action="create",
                    model_label="audit.TimeClockEntry",
                    object_id=open_entry.pk,
                    object_repr=str(open_entry),
                    message="Clocked in.",
                )
                messages.success(request, "You are clocked in.")
                return redirect("staff_time_clock")
        elif action == "clock_out":
            if not open_entry:
                messages.info(request, "You are not clocked in.")
            elif form.is_valid():
                if form.cleaned_data.get("note"):
                    open_entry.note = form.cleaned_data["note"]
                open_entry.clock_out = timezone.now()
                open_entry.clock_out_ip = get_client_ip(request)
                open_entry.save(update_fields=["note", "clock_out", "clock_out_ip", "updated_at"])
                announce_time_clock_event(request.user, "clock_out", note=open_entry.note)
                log_activity(
                    user=request.user,
                    request=request,
                    action="update",
                    model_label="audit.TimeClockEntry",
                    object_id=open_entry.pk,
                    object_repr=str(open_entry),
                    message="Clocked out.",
                )
                messages.success(request, f"Clocked out. Shift length: {open_entry.duration_hours} hours.")
                return redirect("staff_time_clock")
    recent_entries = TimeClockEntry.objects.filter(employee=request.user).order_by("-clock_in")[:20]
    week_start = timezone.now() - timedelta(days=7)
    weekly_hours = sum(
        entry.duration_hours
        for entry in TimeClockEntry.objects.filter(employee=request.user, clock_in__gte=week_start, clock_out__isnull=False)
    )
    return render(request, "audit/staff_time_clock.html", {
        "form": form,
        "open_entry": open_entry,
        "recent_entries": recent_entries,
        "weekly_hours": round(weekly_hours, 2),
        "can_manage_time_clock": can_manage_time_clock(request.user),
    })


@team_member_required
def staff_time_clock_admin(request):
    if not can_manage_time_clock(request.user):
        messages.error(request, "Owner or admin access required.")
        return redirect("staff_time_clock")
    auto_count = auto_clock_out_overdue_entries(request)
    if auto_count:
        messages.info(request, f"Auto clocked out {auto_count} overdue shift{'' if auto_count == 1 else 's'} at 8 hours.")
    staff = list(User.objects.filter(role__in=["employee", "admin"], is_active=True).order_by("first_name", "username"))
    open_entries = {
        entry.employee_id: entry
        for entry in TimeClockEntry.objects.filter(clock_out__isnull=True, employee__in=staff).select_related("employee")
    }
    rows = []
    for employee in staff:
        last_entry = TimeClockEntry.objects.filter(employee=employee).order_by("-clock_in").first()
        rows.append({
            "employee": employee,
            "open_entry": open_entries.get(employee.pk),
            "last_entry": last_entry,
        })
    recent_entries = TimeClockEntry.objects.select_related("employee").order_by("-clock_in")[:80]
    return render(request, "audit/staff_time_clock_admin.html", {
        "rows": rows,
        "recent_entries": recent_entries,
        "open_count": len(open_entries),
    })


@team_member_required
def staff_time_clock_entry_clock_out(request, pk):
    if not can_manage_time_clock(request.user):
        messages.error(request, "Owner or admin access required.")
        return redirect("staff_time_clock")
    entry = get_object_or_404(TimeClockEntry.objects.select_related("employee"), pk=pk)
    if request.method != "POST":
        return redirect("staff_time_clock_admin")
    if entry.clock_out:
        messages.info(request, "That shift is already clocked out.")
        return redirect("staff_time_clock_admin")
    entry.clock_out = timezone.now()
    entry.clock_out_ip = get_client_ip(request)
    entry.save(update_fields=["clock_out", "clock_out_ip", "updated_at"])
    announce_time_clock_event(entry.employee, "admin_clock_out", note=entry.note, actor=request.user)
    log_activity(
        user=request.user,
        request=request,
        action="update",
        model_label="audit.TimeClockEntry",
        object_id=entry.pk,
        object_repr=str(entry),
        message=f"Admin clocked out {entry.employee}.",
    )
    messages.success(request, f"Clocked out {entry.employee.get_full_name() or entry.employee.username}.")
    return redirect("staff_time_clock_admin")


@team_member_required
def staff_time_clock_entry_edit(request, pk):
    if not can_manage_time_clock(request.user):
        messages.error(request, "Owner or admin access required.")
        return redirect("staff_time_clock")
    entry = get_object_or_404(TimeClockEntry.objects.select_related("employee"), pk=pk)
    if request.method == "POST":
        form = TimeClockEntryForm(request.POST, instance=entry)
        if form.is_valid():
            updated = form.save(commit=False)
            if updated.clock_out and not updated.clock_out_ip:
                updated.clock_out_ip = get_client_ip(request)
            updated.save()
            log_activity(
                user=request.user,
                request=request,
                action="update",
                model_label="audit.TimeClockEntry",
                object_id=entry.pk,
                object_repr=str(entry),
                message=f"Edited time clock punch for {entry.employee}.",
            )
            messages.success(request, "Time clock punch updated.")
            return redirect("staff_time_clock_admin")
    else:
        form = TimeClockEntryForm(instance=entry)
    return render(request, "audit/staff_time_clock_entry_form.html", {
        "form": form,
        "entry": entry,
    })
