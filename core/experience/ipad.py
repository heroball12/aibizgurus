"""Authenticated presentation routes for the native iPad client.

The public demo keeps its own routes. An app user agent is never an access token.
"""
from functools import wraps

from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.contrib.auth.views import LoginView
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .access import salesperson


class IPadLoginView(LoginView):
    template_name = "core/experience/ipad_login.html"
    extra_context = {"ipad_app": True}

    def get_success_url(self):
        return reverse("experience_ipad:home")


def private_view(view, *, api=False):
    @never_cache
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not salesperson(request.user):
            if api:
                return JsonResponse({"error": "Sign in with an authorized employee account to continue.",
                                     "code": "signin_required"}, status=403)
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), login_url=reverse("experience_ipad:login"))
            return render(request, "core/experience/ipad_denied.html", status=403)
        request.experience_ipad = True
        return view(request, *args, **kwargs)
    return wrapped


@never_cache
@require_POST
def signout(request):
    logout(request)
    return redirect(reverse("experience_ipad:home"))
