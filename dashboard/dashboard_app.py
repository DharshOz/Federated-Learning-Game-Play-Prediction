"""
dashboard_app.py — Direct launcher for Arcane Clash Dashboard.

Starts the backend server if not running and automatically opens
the real-time web observatory in the default web browser.
"""

import os
import sys
import time

def get_project_root() -> str:
    cur = os.path.dirname(os.path.abspath(__file__))
    while cur and os.path.dirname(cur) != cur:
        if os.path.exists(os.path.join(cur, "Assets")) or os.path.exists(os.path.join(cur, ".env")):
            return cur
        cur = os.path.dirname(cur)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

_ROOT_DIR = get_project_root()
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from backend.server_manager import open_dashboard, is_server_running, start_server_process

def run_dashboard():
    print("=" * 60)
    print("🌐 Launching Arcane Clash Dashboard & Observatory...")
    print("=" * 60)
    if not is_server_running():
        print("[Dashboard] Starting backend server in background...")
        start_server_process()
        time.sleep(0.8)
    open_dashboard()
    print("[Dashboard] Dashboard is active! Press Ctrl+C to stop or close this window.")

if __name__ == "__main__":
    run_dashboard()
