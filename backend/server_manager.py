"""
server_manager.py — Automatic Lifecycle & Browser Integration for Arcane Clash Dashboard.

Ensures the FastAPI backend & dashboard observatory server is automatically running
when the game is launched, and automatically opens the dashboard in the default web browser
when a match concludes (win or defeat) or when requested from the in-game UI.
"""

import os
import sys
import time
import socket
import subprocess
import threading
import webbrowser
import requests

def get_project_root() -> str:
    cur = os.path.dirname(os.path.abspath(__file__))
    while cur and os.path.dirname(cur) != cur:
        if os.path.exists(os.path.join(cur, "Assets")) or os.path.exists(os.path.join(cur, ".env")):
            return cur
        cur = os.path.dirname(cur)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

PROJECT_ROOT = get_project_root()
BACKEND_HOST = os.getenv("HOST", "127.0.0.1")
BACKEND_PORT = int(os.getenv("PORT", 8000))
BACKEND_URL = os.getenv("BACKEND_URL", f"http://localhost:{BACKEND_PORT}").rstrip("/")

_server_process = None
_lock = threading.Lock()

def is_server_running(url: str = None, timeout: float = 0.8) -> bool:
    """Check if the backend observatory server is active and responding."""
    urls = [url] if url else [
        f"http://127.0.0.1:{BACKEND_PORT}",
        f"http://localhost:{BACKEND_PORT}",
    ]
    for u in urls:
        if not u:
            continue
        try:
            r = requests.get(f"{u}/api/stats", timeout=timeout)
            if r.status_code == 200:
                return True
        except Exception:
            pass

    # Socket connect check
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex(("127.0.0.1", BACKEND_PORT))
        s.close()
        return result == 0
    except Exception:
        return False

def start_server_process() -> bool:
    """Start the backend server in an independent background process."""
    global _server_process
    with _lock:
        if is_server_running():
            return True

        if _server_process is not None and _server_process.poll() is None:
            return True

        python_exe = sys.executable
        # Try backend/server.py first, then server.py at root
        server_script = os.path.join(PROJECT_ROOT, "backend", "server.py")
        if not os.path.exists(server_script):
            server_script = os.path.join(PROJECT_ROOT, "server.py")

        creationflags = 0
        if sys.platform == "win32":
            # DETACHED_PROCESS (0x00000008) + CREATE_NO_WINDOW (0x08000000)
            creationflags = 0x00000008 | 0x08000000

        env = os.environ.copy()
        env["PYTHONPATH"] = PROJECT_ROOT + (os.pathsep + env.get("PYTHONPATH", ""))
        env["PYTHONIOENCODING"] = "utf-8"

        log_dir = os.path.join(PROJECT_ROOT, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "server.log")

        try:
            log_fp = open(log_file, "a", encoding="utf-8")
            _server_process = subprocess.Popen(
                [python_exe, server_script],
                cwd=PROJECT_ROOT,
                env=env,
                stdout=log_fp,
                stderr=subprocess.STDOUT,
                creationflags=creationflags
            )
            print(f"[ServerManager] Launched background server process (PID {_server_process.pid})")
        except Exception as e:
            print(f"[ServerManager] Failed to launch background server process: {e}")
            return False

        # Wait up to 5.0s for server to start responding
        start_time = time.time()
        while time.time() - start_time < 5.0:
            if is_server_running(timeout=0.3):
                print(f"[ServerManager] Backend server is live at {BACKEND_URL}")
                return True
            time.sleep(0.2)

        return is_server_running()

def ensure_server_running(url: str = BACKEND_URL) -> bool:
    """Ensure the backend server is running; launch asynchronously if needed."""
    if is_server_running(url):
        return True
    
    # Launch in a background thread to prevent any Pygame frame hitching
    t = threading.Thread(target=start_server_process, daemon=True, name="ServerAutoStart")
    t.start()
    return True

def open_dashboard(url: str = BACKEND_URL):
    """Open the live web dashboard in the user's default browser, starting server if needed."""
    def _open_flow():
        if not is_server_running(url):
            start_server_process()
            time.sleep(0.6)
        try:
            print(f"[Dashboard] Opening live observatory in browser: {url}")
            webbrowser.open(url)
        except Exception as e:
            print(f"[Dashboard] Could not open browser: {e}")

    threading.Thread(target=_open_flow, daemon=True, name="DashboardOpenFlow").start()
