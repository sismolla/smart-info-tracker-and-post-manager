import os
import base64
import hashlib
from django.conf import settings
from cryptography.fernet import Fernet

def get_cipher():
    """
    Returns a Fernet cipher instance based on FIELD_ENCRYPTION_KEY or
    derives a deterministic key from Django's SECRET_KEY if unset.
    """
    key = getattr(settings, 'FIELD_ENCRYPTION_KEY', '')
    if not key:
        # Derive 32-byte urlsafe base64 key from SECRET_KEY
        derived = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(derived)
    elif isinstance(key, str):
        key = key.encode()
        
    return Fernet(key)

def encrypt_value(plaintext: str) -> str:
    """Encrypts a plaintext string and returns a base64 encoded string."""
    if not plaintext:
        return ""
    cipher = get_cipher()
    return cipher.encrypt(plaintext.encode('utf-8')).decode('utf-8')

def decrypt_value(ciphertext: str) -> str:
    """Decrypts a base64 encoded ciphertext string."""
    if not ciphertext:
        return ""
    cipher = get_cipher()
    try:
        return cipher.decrypt(ciphertext.encode('utf-8')).decode('utf-8')
    except Exception:
        # If decryption fails (e.g. key changed), return empty or raw if not encrypted
        return ""
