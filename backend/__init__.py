"""
Arcane Clash — Backend Package.
Provides FastAPI telemetry ingestion, MongoDB/local persistence, and server management.
"""

from .db import Database, get_db
from .client_sync import ClientSyncManager, get_client_sync
from .server_manager import is_server_running, ensure_server_running, open_dashboard
from .server import app, run_server

__all__ = [
    "Database",
    "get_db",
    "ClientSyncManager",
    "get_client_sync",
    "is_server_running",
    "ensure_server_running",
    "open_dashboard",
    "app",
    "run_server",
]
