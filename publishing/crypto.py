"""
Lightweight credential encryption for PublishChannel secrets.
Uses Fernet symmetric encryption keyed from Django's SECRET_KEY.
"""
import base64
import hashlib
from django.conf import settings


def _get_fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    key_material = settings.SECRET_KEY.encode('utf-8')
    # Derive a 32-byte key from the Django secret
    digest = hashlib.sha256(key_material).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns the ciphertext as a str, or plaintext if cryptography not installed."""
    if not plaintext:
        return plaintext
    f = _get_fernet()
    if f is None:
        return plaintext   # graceful degradation
    return f.encrypt(plaintext.encode('utf-8')).decode('utf-8')


def decrypt(ciphertext: str) -> str:
    """Decrypt a ciphertext string. Returns plaintext, or the input if decryption fails."""
    if not ciphertext:
        return ciphertext
    f = _get_fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode('utf-8')).decode('utf-8')
    except Exception:
        # Already plaintext (legacy / non-encrypted) or corrupted — return as-is
        return ciphertext
