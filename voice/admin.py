from django.contrib import admin
from .models import CallLog, SMSLog

@admin.register(CallLog)
class CallLogAdmin(admin.ModelAdmin):
    list_display = ("ai_instance", "from_number", "status", "created_at")
    search_fields = ("from_number", "transcript", "summary")

@admin.register(SMSLog)
class SMSLogAdmin(admin.ModelAdmin):
    list_display = ("ai_instance", "from_number", "created_at")
    search_fields = ("from_number", "body", "response")
