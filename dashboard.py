"""
Arcane Clash — Standalone Dashboard Launcher.
Ensures the backend server is running and automatically opens the live web observatory in your browser.
"""

import os
import sys

_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from dashboard.dashboard_app import run_dashboard

if __name__ == "__main__":
    run_dashboard()
