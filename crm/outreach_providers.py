"""Small server-side transports. No secrets or provider response bodies in logs."""

import base64
import json
import re
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from urllib import error, parse, request

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.urls import reverse
from core.security import decrypt_value

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GOOGLE_SCOPES = f"openid email {GMAIL_SCOPE}"


class OutreachError(Exception):
    def __init__(self, message, *, uncertain=False, status=400):
        super().__init__(message)
        self.uncertain = uncertain
        self.status = status


def google_ready():
    key = settings.FIELD_ENCRYPTION_KEY
    redirect = parse.urlsplit(settings.SALES_GOOGLE_REDIRECT_URI)
    secure_redirect = redirect.scheme == "https" or (
        settings.DEBUG and redirect.hostname in {"localhost", "127.0.0.1"}
    )
    return bool(
        settings.SALES_GOOGLE_CLIENT_ID
        and settings.SALES_GOOGLE_CLIENT_SECRET
        and key
        and not key.startswith("dev-only-")
        and secure_redirect
        and settings.SALES_GOOGLE_DOMAINS
    )


def sms_ready():
    return bool(
        settings.TWILIO_ACCOUNT_SID
        and settings.TWILIO_AUTH_TOKEN
        and re.fullmatch(r"\+[1-9]\d{7,14}", settings.SALES_SMS_FROM_NUMBER)
        and settings.PUBLIC_BASE_URL.startswith("https://")
    )


def email_address(value):
    value = (value or "").strip()
    try:
        validate_email(value)
    except ValidationError:
        raise OutreachError(
            "Add a valid prospect email in Edit details first."
        ) from None
    if len(value) > 254 or any(char in value for char in "\r\n"):
        raise OutreachError("The email address is invalid.")
    return value


def phone_number(value):
    value = (value or "").strip()
    if not re.fullmatch(r"\+?[\d ()\-.]+", value):
        raise OutreachError(
            "Add a valid mobile number in Edit details first. Include a country code for numbers outside the US."
        )
    digits = re.sub(r"\D", "", value)
    if not value.startswith("+"):
        if len(digits) == 10:
            digits = "1" + digits
        elif len(digits) != 11 or not digits.startswith("1"):
            raise OutreachError(
                "Include the country code in the prospect’s mobile number."
            )
    result = "+" + digits
    if not re.fullmatch(r"\+[1-9]\d{7,14}", result):
        raise OutreachError("The prospect’s mobile number is invalid.")
    return result


def google_json(url, *, form=None, payload=None, token=None, sending=False):
    headers = {"Accept": "application/json"}
    data = None
    if form is not None:
        data = parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = request.Request(url, data=data, headers=headers)
    try:
        with request.urlopen(req, timeout=15) as response:
            result = json.loads(response.read(1_000_001))
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except error.HTTPError as exc:
        uncertain = sending and (exc.code >= 500 or exc.code == 408)
        raise OutreachError(
            (
                "Google could not confirm delivery. Check Gmail Sent before creating another message."
                if uncertain
                else "Google rejected the request. Check your mailbox connection and Google Workspace permissions."
            ),
            uncertain=uncertain,
            status=502,
        ) from None
    except (error.URLError, TimeoutError, ValueError, OSError):
        raise OutreachError(
            (
                "Google did not confirm delivery. Check Gmail Sent before creating another message."
                if sending
                else "Could not reach Google. Please try again shortly."
            ),
            uncertain=sending,
            status=502,
        ) from None


def google_token(form):
    return google_json(
        "https://oauth2.googleapis.com/token",
        form={
            "client_id": settings.SALES_GOOGLE_CLIENT_ID,
            "client_secret": settings.SALES_GOOGLE_CLIENT_SECRET,
            **form,
        },
    )


def send_gmail(message, mailbox, display_name):
    refresh = decrypt_value(mailbox.refresh_token)
    if not refresh or not mailbox.active or not google_ready():
        raise OutreachError("Reconnect your Google Workspace mailbox before sending.")
    try:
        tokens = google_token({"grant_type": "refresh_token", "refresh_token": refresh})
    except OutreachError:
        raise OutreachError(
            "Your Google connection could not be refreshed. Reconnect your mailbox, then retry."
        ) from None
    token = tokens.get("access_token")
    if not isinstance(token, str) or not token:
        raise OutreachError("Reconnect your Google Workspace mailbox before sending.")
    mime = EmailMessage()
    mime["From"] = formataddr(
        (re.sub(r"[\r\n]", " ", display_name)[:120], mailbox.email)
    )
    mime["To"] = email_address(message.recipient)
    mime["Subject"] = message.subject
    mime["Message-ID"] = make_msgid(
        idstring=str(message.pk), domain=mailbox.email.split("@")[-1]
    )
    mime.set_content(message.body)
    result = google_json(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        payload={"raw": base64.urlsafe_b64encode(mime.as_bytes()).decode()},
        token=token,
        sending=True,
    )
    if not isinstance(result.get("id"), str) or not result["id"]:
        raise OutreachError(
            "Google did not confirm delivery. Check Gmail Sent before creating another message.",
            uncertain=True,
            status=502,
        )
    return result["id"][:120], "submitted"


def send_sms(message):
    from twilio.base.exceptions import TwilioRestException
    from twilio.http.http_client import TwilioHttpClient
    from twilio.rest import Client

    if not sms_ready():
        raise OutreachError("The company SMS sender has not been configured yet.")
    client = Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN,
        http_client=TwilioHttpClient(timeout=15, max_retries=0),
    )
    params = {
        "to": message.recipient,
        "from_": settings.SALES_SMS_FROM_NUMBER,
        "body": message.body,
        "status_callback": settings.PUBLIC_BASE_URL
        + reverse("outreach_sms_status", args=[message.pk]),
    }
    if settings.SALES_SMS_MESSAGING_SERVICE_SID:
        params["messaging_service_sid"] = settings.SALES_SMS_MESSAGING_SERVICE_SID
    try:
        result = client.messages.create(**params)
    except TwilioRestException as exc:
        uncertain = not exc.status or exc.status >= 500 or exc.status == 408
        if exc.code == 21610:
            from .models import SalesSMSContact

            SalesSMSContact.objects.update_or_create(
                phone=message.recipient, defaults={"opted_out": True}
            )
        raise OutreachError(
            (
                "The SMS provider did not confirm the result. Check its message log before sending again."
                if uncertain
                else "The SMS provider rejected this text. Check the sender, recipient and opt-out status."
            ),
            uncertain=uncertain,
            status=502,
        ) from None
    except Exception:
        raise OutreachError(
            "The SMS provider did not confirm the result. Check its message log before sending again.",
            uncertain=True,
            status=502,
        ) from None
    if not result.sid:
        raise OutreachError(
            "The SMS result is uncertain. Check the provider log before sending again.",
            uncertain=True,
            status=502,
        )
    return result.sid[:120], str(result.status or "queued")[:30]
