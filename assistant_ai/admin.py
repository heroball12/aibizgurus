from django.contrib import admin
from .models import Conversation, Message, KnowledgeDocument

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
