from django.urls import resolve
from .threadlocal import set_current_request, clear_current_request
from .utils import log_activity

SKIP_PREFIXES = ("/static/", "/favicon.ico")
SKIP_NAMES = {"owner_activity_logs"}

class ActivityLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_current_request(request)
        try:
            response = self.get_response(request)
            self.log_request(request, response)
            return response
        finally:
            clear_current_request()

    def log_request(self, request, response):
        if any(request.path.startswith(prefix) for prefix in SKIP_PREFIXES):
            return
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return
        try:
            match = resolve(request.path)
            if match.url_name in SKIP_NAMES:
                return
        except Exception:
            pass

        # Log meaningful navigation/actions. Avoid excessive noise from successful GET admin media/static.
        log_activity(
            user=user,
            request=request,
            action="request",
            message=f"{request.method} {request.path}",
            status_code=getattr(response, "status_code", None),
            metadata={
                "query_string": request.META.get("QUERY_STRING", ""),
                "referer": request.META.get("HTTP_REFERER", ""),
            },
        )
