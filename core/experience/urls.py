from django.urls import path
from . import views
urlpatterns = [
    path("", views.automotive, name="experience_home"),
    path("session/", views.session_start, name="experience_session"),
    path("turn/", views.turn, name="experience_turn"),
    path("action/", views.action, name="experience_action"),
    path("financing/", views.finance, name="experience_finance"),
    path("transcribe/", views.transcribe, name="experience_transcribe"),
    path("speech/", views.speech, name="experience_speech"),
    path("crm/", views.dealership_crm, name="experience_crm"),
    path("crm/state/", views.crm_state, name="experience_crm_state"),
    path("guide/", views.rep_guide, name="experience_guide"),
    path("manage/", views.manage, name="experience_manage"),
    path("qr/", views.qr, name="experience_qr"),
    path("manifest.webmanifest", views.manifest, name="experience_manifest"),
]
