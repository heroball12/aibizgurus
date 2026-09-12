from django.shortcuts import redirect
from django.urls import reverse


class LegacyPasswordMiddleware:
    """Require replacement of the formerly shared staff password on existing sessions."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_employee_or_admin():
            # Cache against the password hash, so an administrator reset is rechecked.
            if request.session.get("checked_password_hash") != user.get_session_auth_hash():
                request.session["legacy_password_reset"] = user.check_password("AIBG123")
                request.session["checked_password_hash"] = user.get_session_auth_hash()
            allowed = {reverse("password_change"), reverse("password_change_done"), reverse("logout")}
            if request.session.get("legacy_password_reset") and request.path not in allowed and not request.path.startswith("/static/"):
                return redirect("password_change")
        return self.get_response(request)


class AuthRequestLimitMiddleware:
    """Bound expensive login, signup and reset requests without account enumeration."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path in {reverse("login"), reverse("signup"), reverse("password_reset"), "/admin/login/"}:
            from core.rate_limits import consume_budget, request_identity
            from django.shortcuts import render
            if not consume_budget("authentication", request_identity(request), limit=30, window=900):
                response = render(request, "accounts/rate_limited.html", status=429)
                response["Retry-After"] = "900"
                return response
        return self.get_response(request)
