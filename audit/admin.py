from django.contrib import admin
from .models import ActivityLog

@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor_username", "actor_role", "action", "path", "model_label", "object_repr", "status_code")
    list_filter = ("action", "actor_role", "created_at", "model_label", "status_code")
    search_fields = ("actor_username", "path", "model_label", "object_repr", "message", "user_agent")
    readonly_fields = [field.name for field in ActivityLog._meta.fields]

    def has_add_permission(self, request):
        return False
