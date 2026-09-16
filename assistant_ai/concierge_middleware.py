"""Allow only public marketing pages inside our same-origin guided browser."""
PUBLIC_VIEWS = {"home", "solutions", "solution_detail", "ai_employees", "industries", "demo", "pricing", "case_studies", "growth_assessment", "consultation_request"}


class ConciergeFrameMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        match = request.resolver_match
        guided_page = request.GET.get("guided") == "1" and match and match.url_name in PUBLIC_VIEWS
        embedded_concierge = request.GET.get("embed") == "1" and match and match.url_name == "concierge"
        if guided_page or embedded_concierge:
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        return response
