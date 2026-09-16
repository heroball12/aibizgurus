from django.urls import path
from . import views, concierge_views
urlpatterns = [
    path("concierge/calls/<uuid:call_id>/text/", concierge_views.text_input, name="concierge_text"),
    path("concierge/calls/<uuid:call_id>/text/status/", concierge_views.text_status, name="concierge_text_status"),
    path("concierge/", concierge_views.concierge_home, name="concierge"),
    path("concierge/start/", concierge_views.start_call, name="concierge_start"),
    path("concierge/calls/<uuid:call_id>/poll/", concierge_views.poll_call, name="concierge_poll"),
    path("concierge/calls/<uuid:call_id>/stop/", concierge_views.stop_call, name="concierge_stop"),
    path("concierge/followup/", concierge_views.submit_followup, name="concierge_followup"),
    path("widget/<slug:slug>/", views.widget, name="widget"),
    path("widget/<slug:slug>/chat/", views.widget_chat_api, name="widget_chat_api"),
]
