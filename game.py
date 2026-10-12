"""
Arcane Clash — Main Game Launcher.
Runs the Turn-Based RPG game and ensures the background backend server and dashboard telemetry are active.
"""

import os
import sys

_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from game.game import Game, main

if __name__ == "__main__":
    main()
