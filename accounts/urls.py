from django.urls import path

from . import views
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy

urlpatterns = [
    path("password-reset/", auth_views.PasswordResetView.as_view(template_name="accounts/password_form.html", email_template_name="accounts/password_reset_email.txt", subject_template_name="accounts/password_reset_subject.txt", extra_context={"heading": "Reset your password", "intro": "Enter your account email and we will send a secure reset link."}), name="password_reset"),
    path("password-reset/sent/", auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_done.html", extra_context={"heading": "Check your email", "intro": "If an active account matches that email, a password reset link is on its way. Check your spam folder too."}), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="accounts/password_form.html", extra_context={"heading": "Choose a new password"}), name="password_reset_confirm"),
    path("reset/complete/", auth_views.PasswordResetCompleteView.as_view(template_name="accounts/password_done.html", extra_context={"heading": "Password updated", "intro": "You can now sign in with your new password."}), name="password_reset_complete"),
    path("password-change/", auth_views.PasswordChangeView.as_view(template_name="accounts/password_form.html", success_url=reverse_lazy("password_change_done"), extra_context={"heading": "Change your password"}), name="password_change"),
    path("password-change/done/", auth_views.PasswordChangeDoneView.as_view(template_name="accounts/password_done.html", extra_context={"heading": "Password updated", "intro": "Your new password is ready to use."}), name="password_change_done"),
    path("signup/", views.signup, name="signup"),
    path("login/", views.RoleAwareLoginView.as_view(), name="login"),
    path("logout/", views.FriendlyLogoutView.as_view(), name="logout"),
]
