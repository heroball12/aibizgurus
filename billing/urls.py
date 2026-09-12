from django.urls import path
from . import views
urlpatterns = [
    path("", views.billing_home, name="billing_home"),
    path("checkout/<str:plan>/", views.create_checkout_session, name="create_checkout_session"),
    path("manage/", views.customer_portal, name="customer_portal"),
    path("webhook/", views.stripe_webhook, name="stripe_webhook"),
    path("success/", views.payment_success, name="payment_success"),
]
