"""
Adaptive Boss Memory & Weighting System for Arcane Clash.

Provides in-match adaptive heuristic weighting that shifts boss action selection
based on the player's rolling action history (last 5 turns).
Isolated module for straightforward tuning or future swap-in of federated ML models.
"""

from collections import deque
import random


class AdaptiveBossMemory:
    """Tracks player actions within a single match and computes adaptive boss action weights."""

    # Baseline weight table for boss actions
    DEFAULT_WEIGHTS = {
        "quick_slash": 40.0,
        "fireball": 20.0,
        "water_arrow": 20.0,
        "water_spell": 15.0,
        "rest": 10.0,
        "enrage": 25.0,
    }

    DEFENSIVE_ACTIONS = {"rest", "heal"}
    AGGRESSIVE_ACTIONS = {"fireball", "fire_spell", "quick_slash", "water_spell", "water_arrow"}
    GUARD_BREAK_ACTIONS = {"enrage", "fireball", "fire_spell"}

    def __init__(self, history_len=5, boost_weight=0.25):
        self.history_len = history_len
        self.boost_weight = boost_weight
        self.history = deque(maxlen=history_len)
        self.base_weights = dict(self.DEFAULT_WEIGHTS)

    def reset(self):
        """Reset in-match history between battles."""
        self.history.clear()

    def record_player_action(self, action_key):
        """Append the player's chosen action to rolling match memory."""
        if action_key:
            self.history.append(action_key.lower())

    def get_recent_history(self):
        """Return list of recent player actions."""
        return list(self.history)

    def compute_action_weights(self, usable_actions, boss_phase=1):
        """
        Calculates normalized selection probabilities for available boss actions.
        Returns:
            chosen_action (str): sampled action key
            weights_snapshot (dict): mapping of action_key -> probability (0.0 to 1.0)
        """
        if not usable_actions:
            usable_actions = ["quick_slash"]

        # Filter available actions according to phase
        eligible = [a for a in usable_actions if a != "enrage" or boss_phase >= 2]
        if not eligible:
            eligible = list(usable_actions)

        # Start with base weights for eligible actions
        raw_weights = {a: float(self.base_weights.get(a, 10.0)) for a in eligible}

        # Analyze recent player tendencies (last 5 actions)
        defensive_count = sum(1 for a in self.history if a in self.DEFENSIVE_ACTIONS)
        aggressive_count = sum(1 for a in self.history if a in self.AGGRESSIVE_ACTIONS)

        total_base = sum(raw_weights.values()) or 1.0

        # Heuristic 1: If player plays defensively 3+ times in last 5 turns -> boost Guard-Breaking/heavy attacks
        if defensive_count >= 3:
            for a in eligible:
                if a in self.GUARD_BREAK_ACTIONS:
                    raw_weights[a] += total_base * self.boost_weight

        # Heuristic 2: If player attacks aggressively 3+ times in last 5 turns -> boost Rest & Recharge / defense
        if aggressive_count >= 3:
            for a in eligible:
                if a in ("rest", "heal"):
                    raw_weights[a] += total_base * self.boost_weight

        # Normalize to probability distribution (summing to 1.0)
        sum_weights = sum(raw_weights.values())
        if sum_weights <= 0:
            sum_weights = 1.0
            raw_weights = {a: 1.0 / len(eligible) for a in eligible}

        probabilities = {a: round(w / sum_weights, 4) for a, w in raw_weights.items()}

        # Sample action based on calculated probabilities
        actions = list(probabilities.keys())
        probs = [probabilities[a] for a in actions]

        # Handle floating-point precision on choice weights
        chosen_action = random.choices(actions, weights=probs, k=1)[0]

        return chosen_action, probabilities
