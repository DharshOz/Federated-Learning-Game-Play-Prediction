"""
auth.py — Cryptographic Password Hashing & User Security Layer for Arcane Clash.

Provides secure password hashing via PBKDF2-HMAC-SHA256 with unique per-user salts,
constant-time verification to prevent timing attacks, and username sanitation.
"""

import hashlib
import secrets
import hmac
import re
import time
from typing import Optional, Tuple, Dict, Any

USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-]{3,24}$")
PBKDF2_ITERATIONS = 100_000

def validate_username(username: str) -> Tuple[bool, str]:
    """Validate username format (3-24 alphanumeric characters, underscores, hyphens)."""
    if not username or not isinstance(username, str):
        return False, "Username cannot be empty."
    clean_username = username.strip()
    if len(clean_username) < 3:
        return False, "Username must be at least 3 characters long."
    if len(clean_username) > 24:
        return False, "Username cannot exceed 24 characters."
    if not USERNAME_REGEX.match(clean_username):
        return False, "Username may only contain letters, numbers, underscores, and hyphens."
    return True, clean_username

def validate_password(password: str) -> Tuple[bool, str]:
    """Validate password minimum complexity."""
    if not password or not isinstance(password, str):
        return False, "Password cannot be empty."
    if len(password) < 4:
        return False, "Password must be at least 4 characters long."
    return True, password

def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Hash a password using PBKDF2-HMAC-SHA256 with 100,000 iterations and a hex salt."""
    if not salt:
        salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS
    ).hex()
    return pwd_hash, salt

def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Constant-time password comparison to prevent timing attacks."""
    try:
        computed_hash, _ = hash_password(password, salt)
        return hmac.compare_digest(computed_hash, expected_hash)
    except Exception:
        return False

def sanitize_user_dict(user: Dict[str, Any]) -> Dict[str, Any]:
    """Strip sensitive fields before returning user dictionary to clients."""
    if not user:
        return {}
    safe = dict(user)
    safe.pop("password_hash", None)
    safe.pop("salt", None)
    safe.pop("_id", None)
    return safe
