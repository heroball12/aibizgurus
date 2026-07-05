from django.urls import path
from . import views
urlpatterns = [
    path("incoming/<slug:slug>/", views.incoming_call, name="incoming_call"),
    path("process/<slug:slug>/<int:call_id>/", views.process_call, name="process_call"),
    path("sms/<slug:slug>/", views.incoming_sms, name="incoming_sms"),
]
