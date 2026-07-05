from django.urls import path

from . import views

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("login/", views.RoleAwareLoginView.as_view(), name="login"),
    path("logout/", views.FriendlyLogoutView.as_view(), name="logout"),
]
