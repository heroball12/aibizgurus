"""Safe diagnostics: never persist an exception message, prompt or credential."""
import re


QUOTA_CODES = {
    "insufficient_quota", "billing_hard_limit_reached", "billing_not_active",
    "organization_spend_limit_exceeded", "project_spend_limit_exceeded",
    "organization_usage_limit_exceeded",
}
KNOWN_CODES = QUOTA_CODES | {
    "invalid_api_key", "insufficient_permissions", "permission_denied",
    "model_not_found", "rate_limit_exceeded", "unsupported_country_region_territory",
    "unsupported_parameter", "unsupported_value", "invalid_request_error",
    "context_length_exceeded", "invalid_model", "server_error",
}
KNOWN_PARAMS = {"model", "temperature", "max_tokens", "max_completion_tokens", "messages", "response_format"}


def provider_error_details(exc):
    """Return only bounded, allowlisted metadata from an OpenAI SDK error."""
    kind = type(exc).__name__
    status = getattr(exc, "status_code", None)
    code = getattr(exc, "code", None)
    param = getattr(exc, "param", None)
    if not isinstance(code, str):
        code = None
    if code in QUOTA_CODES:
        category = "quota"
    elif code == "model_not_found":
        category = "model_access"
    elif status == 401 or kind == "AuthenticationError":
        category = "authentication"
    elif status == 403 or kind == "PermissionDeniedError":
        category = "permission"
    elif status == 404 or kind == "NotFoundError":
        category = "model_access"
    elif status == 429 or kind == "RateLimitError":
        category = "rate_limit"
    elif kind == "APITimeoutError":
        category = "timeout"
    elif kind == "APIConnectionError":
        category = "connection"
    elif status in (400, 422):
        category = "request"
    elif isinstance(status, int) and status >= 500:
        category = "unavailable"
    else:
        category = "unknown"
    details = {"category": category}
    if isinstance(status, int) and 400 <= status <= 599:
        details["http_status"] = status
    if isinstance(code, str) and code in KNOWN_CODES:
        details["provider_code"] = code
    if isinstance(param, str) and param in KNOWN_PARAMS:
        details["parameter"] = param
    request_id = getattr(exc, "request_id", None)
    if isinstance(request_id, str) and re.fullmatch(r"req_[a-fA-F0-9-]{16,64}", request_id):
        details["request_id"] = request_id
    # Some permission rejections supply no error code, just a missing-scope
    # message. Extract a boolean only; never save the message itself.
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        body = body.get("error", body)
        message = body.get("message", "") if isinstance(body, dict) else ""
        if category == "permission" and isinstance(message, str) and re.search(r"Missing scopes:\s*model\.request\b", message):
            details["missing_model_request_scope"] = True
    return details
