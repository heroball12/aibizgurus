from django.urls import path
from . import views
urlpatterns = [
    path("widget/<slug:slug>/", views.widget, name="widget"),
    path("widget/<slug:slug>/chat/", views.widget_chat_api, name="widget_chat_api"),
]
