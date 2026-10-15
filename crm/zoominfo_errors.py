"""Bounded, redacted ZoomInfo diagnostics suitable for the employee workspace."""
import base64
import re
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables


OPERATIONS = {
    "/oauth/v1/token": "Authentication",
    "/data/v1/companies/search": "Company search",
    "/data/v1/contacts/search": "People search",
    "/data/v1/contacts/enrich": "Contact details",
    "/data/v1/lookup/enrich": "Contact field lookup",
    "/data/v1/lookup/intent-topics": "Intent topic lookup",
    "/data/v1/intent/search": "Intent search",
}


class ZoomInfoError(Exception):
    def __init__(self, message, *, uncertain=False, status=None, operation="ZoomInfo request",
                 next_step="", provider_errors=None, reference="", retry_after=None):
        super().__init__(message)
        self.uncertain = uncertain
        self.status = status
        self.diagnostic = {
            "message": message, "operation": operation, "status": status,
            "next_step": next_step, "provider_errors": provider_errors or [],
            "reference": reference, "retry_after": retry_after, "uncertain": uncertain,
            "occurred_at": timezone.now().isoformat(),
        }


@sensitive_variables()
def provider_diagnostics(response, request_options):
    """Read only error fields, never an arbitrary response or request dump.

    Known credentials, authorization values, echoed search values, email addresses,
    phone numbers and URLs are removed before any text is saved or displayed.
    """
    hidden = {settings.ZOOMINFO_CLIENT_ID, settings.ZOOMINFO_CLIENT_SECRET}
    for value in (request_options.get("headers") or {}).values():
        if isinstance(value, str) and value.startswith(("Bearer ", "Basic ")):
            hidden.update((value, value.split(" ", 1)[1]))
    auth = request_options.get("auth")
    if isinstance(auth, tuple):
        hidden.update(auth)
        hidden.add(base64.b64encode(":".join(auth).encode()).decode())

    def collect(value):
        if isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, str) and len(value) >= 3:
            hidden.add(value)
        elif isinstance(value, int) and value >= 100000:
            hidden.add(str(value))

    # Schema names/field names are useful diagnostics; redact only filter values.
    body = request_options.get("json") or {}
    if isinstance(body, dict):
        data = body.get("data") or {}
        if isinstance(data, dict):
            attributes = data.get("attributes") or {}
            if isinstance(attributes, dict):
                collect({k: v for k, v in attributes.items() if k not in {"outputFields", "requiredFields"}})
    collect(request_options.get("params") or {})
    hidden = sorted({x for value in hidden if isinstance(value, str) and value
                     for x in (value, quote(value, safe=""))}, key=len, reverse=True)

    def clean(value, limit=500):
        if not isinstance(value, str) or len(value) > 8000:
            return ""
        for secret in hidden:
            value = value.replace(secret, "[redacted]")
        value = re.sub(r"(?i)\b(?:bearer|basic)\s+\S+", "[redacted authorization]", value)
        value = re.sub(r"(?i)\b(?:client[_ -]?secret|access[_ -]?token|refresh[_ -]?token|password|api[_ -]?key)\b[\s\"':=]+[^\s,;]+", "[redacted credential]", value)
        value = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?", "[redacted token]", value)
        value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted email]", value)
        value = re.sub(r"(?i)https?://[^\s<>]+", "[redacted URL]", value)
        value = re.sub(r"(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)", "[redacted number]", value)
        value = " ".join(re.sub(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]", " ", value).split())
        return value[:limit] + ("…" if len(value) > limit else "")

    def identifier(value):
        text = clean(value, 128)
        return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", text) else ""

    errors = []
    try:
        payload = response.json() if len(response.content) <= 64_000 else {}
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    entries = payload.get("errors")
    if not isinstance(entries, list):
        entries = []
    # OAuth uses error/error_description; the Data API uses JSON:API errors.
    if isinstance(payload.get("error"), str):
        entries = [{"code": payload["error"], "detail": payload.get("error_description", "")}]
    elif isinstance(payload.get("errorCode"), str):
        entries = [{"code": payload["errorCode"], "detail": payload.get("errorSummary", ""), "id": payload.get("errorId", "")}]
    elif not entries and (payload.get("title") or payload.get("detail")):
        entries = [payload]
    for item in entries[:3]:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        source = source if isinstance(source, dict) else {}
        entry = {
            "code": identifier(item.get("code")), "title": clean(item.get("title"), 180),
            "detail": clean(item.get("detail")), "reference": identifier(item.get("id")),
            "field": clean(source.get("pointer") or source.get("parameter") or source.get("header"), 180),
        }
        if any(entry.values()):
            errors.append(entry)
    reference = ""
    for name in ("X-Request-ID", "X-Correlation-ID", "Request-ID"):
        reference = identifier(response.headers.get(name))
        if reference:
            break
    return errors, reference


@sensitive_variables()
def http_error(response, path, request_options, *, paid=False):
    status = response.status_code
    errors, reference = provider_diagnostics(response, request_options)
    operation = OPERATIONS.get(path, "ZoomInfo request")
    if status == 401:
        message = "ZoomInfo rejected authentication."
        next_step = "Check that the Client ID and active Client Secret in Render belong to the same ZoomInfo app."
    elif status == 403:
        message = "ZoomInfo denied access to this operation."
        next_step = "Check the app scopes, delegated user's API access and account entitlements for this operation."
        if "intent" in path:
            next_step = "Ask ZoomInfo to verify Intent API entitlement for the delegated user and app, including api:data:intent and api:data:lookup. This response alone does not prove which permission is missing."
    elif status == 429:
        message = "ZoomInfo rejected the request because of an account or request limit."
        next_step = "Follow the provider's explanation below. Wait for a rate limit to reset; if credits or an allowance are exhausted, check usage with your ZoomInfo administrator."
    elif status in (400, 422):
        message = "ZoomInfo rejected the request."
        next_step = "Check the field and provider explanation below, then adjust the filters or requested field access."
    elif status >= 500:
        message = "ZoomInfo returned a server error."
        next_step = "Try again later. If this continues, share the error reference and time with ZoomInfo support."
    else:
        message = "ZoomInfo could not complete this request."
        next_step = "Ask the owner to review the HTTP status and provider explanation below."
    codes = {e["code"] for e in errors}
    if "invalid_scope" in codes:
        next_step = "Check that this ZoomInfo app and its delegated user can request the required API scopes."
    elif "invalid_client" in codes:
        next_step = "Check the Client ID and active Client Secret in Render. Both must belong to the same ZoomInfo app."
    delay = str(response.headers.get("Retry-After", ""))
    retry_after = min(int(delay), 86400) if re.fullmatch(r"[0-9]{1,7}", delay) else None
    return ZoomInfoError(message, status=status, operation=operation, next_step=next_step,
                         provider_errors=errors, reference=reference, retry_after=retry_after,
                         uncertain=paid and (status >= 500 or 300 <= status < 400))
