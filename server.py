"""
Arcane Clash — Backend Server & Dashboard Launcher.
Runs the FastAPI telemetry and real-time Federated Learning observatory server.
"""

import os
import sys

_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from backend.server import app, run_server

if __name__ == "__main__":
    run_server()
