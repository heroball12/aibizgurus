"""Third-party marketing tags belong on public production pages only."""

ZOOMINFO_PUBLIC_PAGES = frozenset({
    "home", "solutions", "solution_detail", "ai_employees", "industries",
    "demo", "cannabis_knowledge", "experience_home", "pricing", "case_studies",
    "growth_assessment", "consultation_request", "concierge", "concierge_terms",
})


def zoominfo_enabled(request):
    match = getattr(request, "resolver_match", None)
    host = request.get_host().split(":", 1)[0].lower()
    return (host in {"aibiz.guru", "www.aibiz.guru"}
            and getattr(match, "url_name", None) in ZOOMINFO_PUBLIC_PAGES
            and not getattr(getattr(request, "user", None), "is_authenticated", False))
