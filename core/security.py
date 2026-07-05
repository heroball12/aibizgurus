import base64
import hashlib
from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken

def _fernet():
    raw = settings.FIELD_ENCRYPTION_KEY.encode()
    if len(raw) == 44:
        key = raw
    else:
        key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)

def encrypt_value(value):
    if value is None or value == "":
        return ""
    return _fernet().encrypt(str(value).encode()).decode()

def decrypt_value(value):
    if not value:
        return ""
    try:
        return _fernet().decrypt(str(value).encode()).decode()
    except InvalidToken:
        return ""

def mask_value(value):
    if not value:
        return ""
    s = str(value)
    return f"{s[:4]}...{s[-4:]}" if len(s) > 8 else "****"
