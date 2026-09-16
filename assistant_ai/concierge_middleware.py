"""Allow only public marketing pages inside our same-origin guided browser."""
PUBLIC_VIEWS = {"home", "solutions", "solution_detail", "ai_employees", "industries", "demo", "pricing", "case_studies", "growth_assessment", "consultation_request"}


class ConciergeFrameMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        match = request.resolver_match
        if request.GET.get("guided") == "1" and match and match.url_name in PUBLIC_VIEWS:
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        return response
