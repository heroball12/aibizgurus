from django.contrib import admin
from core.models import DemoExperience, DemoRevision, DemoSession, DemoFeedback, DemoRepAccess


@admin.register(DemoExperience)
class ExperienceAdmin(admin.ModelAdmin):
    list_display = ("name", "published", "public_access", "current_revision")
    readonly_fields = ("slug", "profile_slug", "current_revision")


@admin.register(DemoRevision)
class RevisionAdmin(admin.ModelAdmin):
    list_display = ("experience", "version", "created_at")
    readonly_fields = ("experience", "version", "content", "created_at", "created_by")
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DemoSession)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("id", "scenario", "rep", "source", "turns", "created_at", "ended_at")
    list_filter = ("scenario", "source")
    readonly_fields = tuple(f.name for f in DemoSession._meta.fields)
    exclude = ("browser_key", "protocol", "lease")
    def has_add_permission(self, request):
        return False


@admin.register(DemoFeedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("category", "rep", "resolved", "created_at")
    readonly_fields = ("session", "rep", "category", "notes", "created_at")


@admin.register(DemoRepAccess)
class AccessAdmin(admin.ModelAdmin):
    list_display = ("user", "enabled")
