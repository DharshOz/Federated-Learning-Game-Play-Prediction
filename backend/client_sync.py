"""
client_sync.py — Universal Background Telemetry & Backend Sync for Arcane Clash.

Enables universal telemetry: transmits heartbeats (live player tracking)
and post-match data (metadata, gameplay logs, extracted features, predictions)
to the configured backend URL in .env without blocking Pygame gameplay.
"""

import os
import sys
import json
import time
import socket
import platform
import threading
import requests
from dotenv import load_dotenv

def get_project_root() -> str:
    cur = os.path.dirname(os.path.abspath(__file__))
    while cur and os.path.dirname(cur) != cur:
        if os.path.exists(os.path.join(cur, "Assets")) or os.path.exists(os.path.join(cur, ".env")):
            return cur
        cur = os.path.dirname(cur)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

_ROOT_DIR = get_project_root()
load_dotenv(os.path.join(_ROOT_DIR, ".env"))

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
DEFAULT_TIMEOUT = 3.0

def get_client_metadata() -> dict:
    """Capture non-invasive client environment metadata for federated analytics."""
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "unknown_host"

    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "python_version": platform.python_version(),
        "hostname_hash": hostname[:8],
        "client_timestamp": time.time(),
        "game_version": "2.0-fl",
    }

class ClientSyncManager:
    """Background manager handling non-blocking HTTP sync to backend."""

    def __init__(self, backend_url: str = BACKEND_URL):
        self.backend_url = backend_url
        self.player_id = None
        self._heartbeat_timer = None
        self._running = False
        self._lock = threading.Lock()

    def start_heartbeat_loop(self, player_id: str, hero_class: str = "Unknown"):
        """Start a periodic daemon thread sending heartbeats every 15s."""
        self.player_id = player_id
        if self._running:
            return
        self._running = True

        def _loop():
            while self._running:
                try:
                    self.send_heartbeat(self.player_id, hero_class)
                except Exception:
                    pass
                time.sleep(15)

        t = threading.Thread(target=_loop, daemon=True, name="HeartbeatThread")
        t.start()

    def stop_heartbeat_loop(self):
        self._running = False

    def send_disconnect(self, player_id: str = None):
        """Notify backend immediately that the player has disconnected/closed game."""
        self._running = False
        pid = player_id or self.player_id
        if not pid:
            return
        try:
            requests.post(
                f"{self.backend_url}/api/heartbeat/disconnect",
                json={"player_id": pid},
                timeout=1.5
            )
        except Exception:
            pass

    def send_heartbeat(self, player_id: str, hero_class: str = "Unknown", status: str = "playing"):
        """Ping the backend with active status."""
        def _post():
            try:
                payload = {
                    "player_id": player_id,
                    "hero_class": hero_class,
                    "status": status,
                    "timestamp": time.time(),
                    "metadata": get_client_metadata(),
                }
                requests.post(
                    f"{self.backend_url}/api/heartbeat",
                    json=payload,
                    timeout=DEFAULT_TIMEOUT
                )
            except Exception:
                # Silently fail if backend is offline so gameplay is unaffected
                pass

        threading.Thread(target=_post, daemon=True).start()

    def send_match_payload(self, match_payload: dict, prediction: dict):
        """Asynchronously send completed match data + prediction to backend."""
        def _post():
            try:
                data = dict(match_payload)
                data["prediction"] = prediction
                data["client_metadata"] = get_client_metadata()
                
                resp = requests.post(
                    f"{self.backend_url}/api/matches",
                    json=data,
                    timeout=5.0
                )
                if resp.status_code in (200, 201):
                    match_id = match_payload.get('summary', {}).get('match_id', 'unknown')
                    print(f"[ClientSync] Match {match_id} successfully synced to backend.")
            except Exception:
                # Graceful degradation: local gameplay is always preserved
                pass

        threading.Thread(target=_post, daemon=True).start()

_GLOBAL_SYNC = None

def get_client_sync() -> ClientSyncManager:
    global _GLOBAL_SYNC
    if _GLOBAL_SYNC is None:
        _GLOBAL_SYNC = ClientSyncManager()
    return _GLOBAL_SYNC
