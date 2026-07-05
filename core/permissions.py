from django.contrib.auth.decorators import user_passes_test
from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

def employee_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_employee_or_admin():
            messages.error(request, "Employee access required.")
            return redirect("portal_home")
        return view(request, *args, **kwargs)
    return wrapper


def owner_required(view_func):
    return user_passes_test(lambda u: u.is_authenticated and u.is_owner())(view_func)
