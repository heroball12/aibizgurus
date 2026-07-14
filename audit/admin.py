from django.contrib import admin
from .models import ActivityLog, StaffMessage, StaffMessageParticipant, StaffMessageThread, TimeClockEntry

@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor_username", "actor_role", "action", "path", "model_label", "object_repr", "status_code")
    list_filter = ("action", "actor_role", "created_at", "model_label", "status_code")
    search_fields = ("actor_username", "path", "model_label", "object_repr", "message", "user_agent")
    readonly_fields = [field.name for field in ActivityLog._meta.fields]

    def has_add_permission(self, request):
        return False


class StaffMessageParticipantInline(admin.TabularInline):
    model = StaffMessageParticipant
    extra = 0
    autocomplete_fields = ("user",)


class StaffMessageInline(admin.TabularInline):
    model = StaffMessage
    extra = 0
    autocomplete_fields = ("sender",)
    readonly_fields = ("created_at",)


@admin.register(StaffMessageThread)
class StaffMessageThreadAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "is_group", "created_by", "updated_at", "created_at")
    list_filter = ("is_group", "created_at", "updated_at")
    search_fields = ("title", "participants__user__username", "participants__user__email", "messages__body")
    autocomplete_fields = ("created_by",)
    inlines = [StaffMessageParticipantInline, StaffMessageInline]


@admin.register(StaffMessage)
class StaffMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "thread", "sender", "created_at")
    list_filter = ("created_at",)
    search_fields = ("body", "sender__username", "sender__email", "thread__title")
    autocomplete_fields = ("thread", "sender")


@admin.register(TimeClockEntry)
class TimeClockEntryAdmin(admin.ModelAdmin):
    list_display = ("employee", "clock_in", "clock_out", "duration_hours", "note")
    list_filter = ("clock_in", "clock_out")
    search_fields = ("employee__username", "employee__email", "employee__first_name", "employee__last_name", "note")
    autocomplete_fields = ("employee",)
