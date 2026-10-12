"""
auth_manager.py — Client-side Player Authentication & Session Coordinator.

Manages user login/registration for the Arcane Clash game client.
Seamlessly syncs credentials with the backend REST API, falling back to
the resilient local database cache when operating in standalone mode.
"""

import os
import sys
import json
import time
import requests
from typing import Optional, Tuple, Dict, Any

def get_project_root() -> str:
    cur = os.path.dirname(os.path.abspath(__file__))
    while cur and os.path.dirname(cur) != cur:
        if os.path.exists(os.path.join(cur, "Assets")) or os.path.exists(os.path.join(cur, ".env")):
            return cur
        cur = os.path.dirname(cur)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

PROJECT_ROOT = get_project_root()
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

SESSION_FILE = os.path.join(PROJECT_ROOT, ".user_session.json")

class AuthManager:
    """Manages player authentication session and credential verification."""

    def __init__(self, backend_url: str = "http://localhost:8000"):
        self.backend_url = backend_url.rstrip("/")
        self.current_user: Optional[str] = None
        self.user_data: Dict[str, Any] = {}
        self._load_saved_session()

    def _load_saved_session(self):
        """Restore active session if remembered."""
        if os.path.exists(SESSION_FILE):
            try:
                with open(SESSION_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    uname = data.get("username")
                    if uname and data.get("remember", True):
                        self.current_user = uname
                        self.user_data = data
                        self._sync_player_id(uname)
            except Exception:
                pass

    def _save_session(self, username: str, user_dict: dict, remember: bool = True):
        """Persist user session to disk."""
        self.current_user = username
        self.user_data = user_dict or {}
        self.user_data["username"] = username
        self.user_data["remember"] = remember
        self.user_data["saved_at"] = time.time()
        try:
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(self.user_data, f, indent=2)
        except Exception:
            pass
        self._sync_player_id(username)

    def _sync_player_id(self, username: str):
        """Update logger and sync modules with authenticated username."""
        try:
            from game.logger import set_active_player_id
            set_active_player_id(username)
        except Exception:
            pass

    def is_logged_in(self) -> bool:
        """Check if an identified user session exists."""
        return bool(self.current_user)

    def get_username(self) -> Optional[str]:
        """Return currently active username."""
        return self.current_user

    def login(self, username: str, password: str, remember: bool = True) -> Tuple[bool, str]:
        """
        Authenticate player credentials.
        First attempts remote backend server; if unavailable, uses local database directly.
        """
        username = (username or "").strip()
        password = password or ""
        if not username:
            return False, "Please enter your username."
        if not password:
            return False, "Please enter your password."

        # 1. Try backend API
        try:
            resp = requests.post(
                f"{self.backend_url}/api/auth/login",
                json={"username": username, "password": password},
                timeout=2.0
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("status") == "success":
                user_info = data.get("user", {})
                self._save_session(username, user_info, remember)
                return True, data.get("message", f"Welcome back, {username}!")
            elif resp.status_code == 401 or resp.status_code == 400:
                return False, data.get("message", "Incorrect credentials.")
        except Exception:
            # Backend not reachable; fallback to direct DB instance
            pass

        # 2. Local database fallback
        try:
            from backend.db import get_db
            db = get_db()
            success, msg, user_doc = db.authenticate_user(username, password)
            if success:
                self._save_session(username, user_doc, remember)
                return True, msg
            return False, msg
        except Exception as e:
            return False, f"Login error: {e}"

    def register(self, username: str, password: str, remember: bool = True) -> Tuple[bool, str]:
        """
        Create a new player account with username and password.
        Attempts remote backend first; falls back to local database.
        """
        username = (username or "").strip()
        password = password or ""
        if not username:
            return False, "Please enter a username."
        if not password:
            return False, "Please enter a password."

        # 1. Try backend API
        try:
            resp = requests.post(
                f"{self.backend_url}/api/auth/register",
                json={"username": username, "password": password},
                timeout=2.0
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("status") == "success":
                user_info = data.get("user", {})
                self._save_session(username, user_info, remember)
                return True, data.get("message", f"Account created! Welcome, {username}!")
            elif resp.status_code == 400:
                return False, data.get("message", "Registration failed.")
        except Exception:
            pass

        # 2. Local database fallback
        try:
            from backend.db import get_db
            db = get_db()
            success, msg, user_doc = db.register_user(username, password)
            if success:
                self._save_session(username, user_doc, remember)
                return True, msg
            return False, msg
        except Exception as e:
            return False, f"Registration error: {e}"

    def logout(self):
        """Clear active user session."""
        self.current_user = None
        self.user_data = {}
        if os.path.exists(SESSION_FILE):
            try:
                os.remove(SESSION_FILE)
            except Exception:
                pass
        try:
            from game.logger import set_active_player_id, get_or_create_player_id
            set_active_player_id(get_or_create_player_id())
        except Exception:
            pass

    def guest_login(self) -> str:
        """Create a temporary guest player identity without credentials."""
        import uuid
        guest_name = f"guest_{uuid.uuid4().hex[:6]}"
        self.current_user = guest_name
        self.user_data = {"username": guest_name, "is_guest": True}
        self._sync_player_id(guest_name)
        return guest_name

_GLOBAL_AUTH = None

def get_auth_manager() -> AuthManager:
    global _GLOBAL_AUTH
    if _GLOBAL_AUTH is None:
        _GLOBAL_AUTH = AuthManager()
    return _GLOBAL_AUTH
