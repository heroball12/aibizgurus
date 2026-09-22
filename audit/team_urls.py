from django.urls import path

from . import team_views, chat_views


urlpatterns = [
    path("messages/preferences/", chat_views.preferences, name="staff_notification_preferences"),
    path("messages/read-all/", chat_views.read_all, name="staff_messages_read_all"),
    path("messages/<int:pk>/send/", chat_views.send, name="staff_message_send"),
    path("messages/<int:pk>/read/", chat_views.read, name="staff_message_read"),
    path("messages/<int:pk>/mute/", chat_views.mute, name="staff_message_mute"),
    path("messages/", team_views.staff_messages, name="staff_messages"),
    path("messages/new/", team_views.staff_message_create, name="staff_message_create"),
    path("messages/summary/", chat_views.summary, name="staff_message_summary"),
    path("messages/reactions/<int:pk>/", team_views.staff_message_react, name="staff_message_react"),
    path("messages/<int:pk>/", team_views.staff_message_thread, name="staff_message_thread"),
    path("messages/<int:pk>/feed/", chat_views.feed, name="staff_message_feed"),
    path("messages/attachments/<int:pk>/", team_views.staff_message_attachment, name="staff_message_attachment"),
    path("time-clock/", team_views.staff_time_clock, name="staff_time_clock"),
    path("time-clock/admin/", team_views.staff_time_clock_admin, name="staff_time_clock_admin"),
    path("time-clock/admin/entries/<int:pk>/edit/", team_views.staff_time_clock_entry_edit, name="staff_time_clock_entry_edit"),
    path("time-clock/admin/entries/<int:pk>/clock-out/", team_views.staff_time_clock_entry_clock_out, name="staff_time_clock_entry_clock_out"),
]
