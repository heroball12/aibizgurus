from django.urls import path
from . import views
urlpatterns = [
    path("", views.portal_home, name="portal_home"),
    path("business-profile/", views.business_profile, name="business_profile"),
    path("assistants/<int:pk>/", views.assistant_settings, name="assistant_settings"),
    path("integrations/", views.integrations, name="integrations"),
    path("leads/", views.client_leads, name="client_leads"),
    path("conversations/", views.client_conversations, name="client_conversations"),
    path("conversations/<int:pk>/", views.client_conversation_detail, name="client_conversation_detail"),
    path("demo-setup/", views.demo_setup_guide, name="demo_setup_guide"),
    path("ops/client/<int:client_id>/", views.ops_client_detail, name="ops_client_detail"),
]
