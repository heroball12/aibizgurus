from django.urls import path
from . import views
from .ipad import IPadLoginView, private_view, signout

app_name = "experience_ipad"
urlpatterns = [
    path("login/", IPadLoginView.as_view(), name="login"),
    path("", private_view(views.automotive), name="home"),
    path("session/", private_view(views.session_start, api=True), name="session"),
    path("turn/", private_view(views.turn, api=True), name="turn"),
    path("action/", private_view(views.action, api=True), name="action"),
    path("financing/", private_view(views.finance, api=True), name="finance"),
    path("service/", private_view(views.service, api=True), name="service"),
    path("transcribe/", private_view(views.transcribe, api=True), name="transcribe"),
    path("speech/", private_view(views.speech, api=True), name="speech"),
    path("crm/", private_view(views.dealership_crm), name="crm"),
    path("crm/state/", private_view(views.crm_state, api=True), name="crm_state"),
    path("guide/", private_view(views.rep_guide), name="guide"),
    path("qr/", private_view(views.qr), name="qr"),
    path("signout/", signout, name="signout"),
]
