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

from .forms import StaffMessageForm, StaffMessageThreadForm, TimeClockNoteForm
from .models import StaffMessage, StaffMessageAttachment, StaffMessageParticipant, StaffMessageThread, TimeClockEntry
from .utils import get_client_ip, log_activity


User = get_user_model()
ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".rtf",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ppt", ".pptx", ".zip",
}
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 6


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
    threads = team_threads_for_user(request.user)
    return render(request, "audit/staff_messages.html", {
        "page_obj": paginate(request, threads, 30),
        "can_view_all": can_view_all_staff_messages(request.user),
    })


@team_member_required
def staff_message_create(request):
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
                    object_repr=thread.display_title(),
                    message="Created internal staff message thread.",
                )
                messages.success(request, "Message thread created.")
                return redirect("staff_message_thread", pk=thread.pk)
        for error in file_errors:
            form.add_error(None, error)
    else:
        form = StaffMessageThreadForm(user=request.user)
    return render(request, "audit/staff_message_form.html", {"form": form})


@team_member_required
def staff_message_thread(request, pk):
    thread = get_thread_for_user(request.user, pk)
    form = StaffMessageForm()
    if request.method == "POST":
        form = StaffMessageForm(request.POST)
        files = request.FILES.getlist("attachments")
        file_errors = validate_uploaded_attachments(files)
        if form.is_valid() and not file_errors:
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
                    object_repr=thread.display_title(),
                    message="Sent internal staff message.",
                )
                return redirect("staff_message_thread", pk=thread.pk)
        for error in file_errors:
            form.add_error(None, error)
    messages_qs = thread.messages.select_related("sender").prefetch_related("attachments").order_by("created_at")
    sidebar_threads = team_threads_for_user(request.user)[:40]
    mark_thread_read(thread, request.user)
    return render(request, "audit/staff_message_thread.html", {
        "thread": thread,
        "thread_messages": messages_qs,
        "sidebar_threads": sidebar_threads,
        "form": form,
        "can_view_all": can_view_all_staff_messages(request.user),
        "is_observer": can_view_all_staff_messages(request.user) and not thread.participants.filter(user=request.user).exists(),
    })


@team_member_required
def staff_message_feed(request, pk):
    thread = get_thread_for_user(request.user, pk)
    mark_thread_read(thread, request.user)
    items = []
    for message in thread.messages.select_related("sender").prefetch_related("attachments").order_by("created_at"):
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
        })
    return JsonResponse({"messages": items, "thread_updated": thread.updated_at.isoformat()})


@team_member_required
def staff_message_summary(request):
    threads = list(team_threads_for_user(request.user)[:8])
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
            "title": thread.display_title(),
            "participants": thread.participant_names(),
            "url": request.build_absolute_uri(reverse("staff_message_thread", args=[thread.pk])),
            "unread_count": unread_count,
            "updated": timezone.localtime(thread.updated_at).strftime("%b %-d, %-I:%M %p"),
            "last_sender": sender_name,
            "last_body": last_message.body[:140] if last_message else "No messages yet.",
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
