from django.contrib import admin
from .models import BillingCustomer

@admin.register(BillingCustomer)
class BillingCustomerAdmin(admin.ModelAdmin):
    list_display = ("client", "plan", "status", "stripe_customer_id", "created_at")
    search_fields = ("client__business_name", "stripe_customer_id", "stripe_subscription_id")
