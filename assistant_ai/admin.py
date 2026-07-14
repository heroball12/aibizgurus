from django.contrib import admin
from .models import AssistantConfiguration, AssistantRole, Conversation, Message, KnowledgeDocument, UsageRecord

class MessageInline(admin.TabularInline):
    model = Message
    extra = 0

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("ai_instance", "customer_name", "customer_phone", "channel", "created_at", "updated_at")
    search_fields = ("customer_name", "customer_phone", "customer_email", "summary", "messages__content")
    list_filter = ("channel", "created_at", "updated_at")
    inlines = [MessageInline]

@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "ai_instance", "processed_status", "created_at")
    search_fields = ("title", "content")


@admin.register(AssistantRole)
class AssistantRoleAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "is_active", "created_at")
    search_fields = ("key", "name", "description")
    list_filter = ("is_active",)


@admin.register(AssistantConfiguration)
class AssistantConfigurationAdmin(admin.ModelAdmin):
    list_display = ("role", "version", "model", "temperature", "is_active", "created_at")
    search_fields = ("role__name", "system_instructions")
    list_filter = ("role", "is_active", "model")
    readonly_fields = ("created_at",)


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ("assistant_role", "model", "status", "total_tokens", "user", "client", "created_at")
    search_fields = ("assistant_role", "model", "error_code", "user__username", "client__business_name")
    list_filter = ("assistant_role", "status", "model", "created_at")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
