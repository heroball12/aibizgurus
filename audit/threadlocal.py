import threading

_local = threading.local()

def set_current_request(request):
    _local.request = request

def clear_current_request():
    if hasattr(_local, "request"):
        delattr(_local, "request")

def get_current_request():
    return getattr(_local, "request", None)

def get_current_user():
    request = get_current_request()
    if not request:
        return None
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return user
    return None
