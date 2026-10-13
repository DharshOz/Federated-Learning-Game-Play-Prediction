"""
predictor.py — Real-time Playstyle Predictor for Arcane Clash.

Loads the trained PyTorch PlaystyleClassifier and fitted feature scaler to
classify player attack style immediately following match completion (win or defeat).
"""

import os
import sys
import numpy as np
import torch
import joblib
from typing import Any, Optional, Dict, List

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

try:
    from .extract_features import extract_match_features
    from .model import PlaystyleClassifier, PERSONA_LABELS, LABEL_TO_IDX, IDX_TO_LABEL
except (ImportError, ValueError):
    from extract_features import extract_match_features
    from model import PlaystyleClassifier, PERSONA_LABELS, LABEL_TO_IDX, IDX_TO_LABEL

def _find_file(filename: str) -> str:
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), filename),
        os.path.join(PROJECT_ROOT, "model", filename),
        os.path.join(PROJECT_ROOT, filename),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]

MODEL_PATH     = _find_file("fl_global_model.pt") if os.path.exists(_find_file("fl_global_model.pt")) else _find_file("playstyle_classifier.pt")
SCALER_PATH    = _find_file("feature_scaler.joblib")
NOTEBOOK_SOURCE = "train_and_predict_playstyle.ipynb"

# Archetype metadata for rich UI and dashboard display
PERSONA_PROFILES = {
    "Aggressive": {
        "title": "Relentless Berserker",
        "badge_color": (255, 75, 90),
        "badge_color_hex": "#FF4757",
        "description": "Favors immediate high-damage spells and relentless pressure, delaying healing until critical health.",
        "icon": "⚔️",
        "key_traits": ["High Fireball & Fire Spell usage", "Low heal HP threshold (<20%)", "High damage output", "Low counter-play focus"]
    },
    "Defensive": {
        "title": "Tactical Guardian",
        "badge_color": (46, 213, 115),
        "badge_color_hex": "#2ED573",
        "description": "Anticipates boss telegraphs with precise soft-counters and maintains high health reserves via proactive recovery.",
        "icon": "🛡️",
        "key_traits": ["High counter-play rate (>60%)", "Frequent Rest & Heal", "High heal trigger HP (>50%)", "Consistent resource buffer"]
    },
    "Optimal": {
        "title": "Grand Strategist",
        "badge_color": (155, 89, 182),
        "badge_color_hex": "#9B59B6",
        "description": "Methodically balances resource thresholds (XP>80, Power>50) before unleashing high-value bursts and tactical counters.",
        "icon": "⚡",
        "key_traits": ["Balanced spell rotation", "High XP/Power management", "Adapts counter-play in phase 2", "Optimal damage-trade ratio"]
    },
    "Random": {
        "title": "Wildcard Sorcerer",
        "badge_color": (255, 165, 2),
        "badge_color_hex": "#FFA502",
        "description": "Exhibits unpredictable spell variety and high action entropy without adhering to rigid tactical loops.",
        "icon": "🎲",
        "key_traits": ["High Shannon action entropy", "Even spread of all actions", "Low repeat rate", "Uncorrelated counter timing"]
    }
}

class PlaystylePredictor:
    """Singleton/Cached predictor that evaluates completed matches."""

    def __init__(self, model_path=None, scaler_path=None):
        if model_path is None:
            fl_path = _find_file("fl_global_model.pt")
            base_path = _find_file("playstyle_classifier.pt")
            self.model_path = fl_path if os.path.exists(fl_path) else base_path
        else:
            self.model_path = model_path
        self.scaler_path = scaler_path or _find_file("feature_scaler.joblib")
        self.model = None
        self.scaler = None
        self.feat_cols = None
        self._load()

    def reload(self):
        """Reload the latest global model checkpoint from disk."""
        fl_path = _find_file("fl_global_model.pt")
        base_path = _find_file("playstyle_classifier.pt")
        self.model_path = fl_path if os.path.exists(fl_path) else base_path
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.scaler_path):
                self.scaler = joblib.load(self.scaler_path)
            
            if os.path.exists(self.model_path):
                ckpt = torch.load(self.model_path, map_location="cpu")
                if isinstance(ckpt, dict) and "model_state_dict" in ckpt:
                    state_dict = ckpt["model_state_dict"]
                    input_dim = ckpt.get("input_dim", 49)
                    hidden_dim = ckpt.get("hidden_dim", 32)
                    num_classes = ckpt.get("num_classes", len(PERSONA_LABELS))
                    self.feat_cols = ckpt.get("feat_cols")
                else:
                    state_dict = ckpt
                    input_dim = state_dict["net.0.weight"].shape[1] if "net.0.weight" in state_dict else 49
                    hidden_dim = state_dict["net.0.weight"].shape[0] if "net.0.weight" in state_dict else 32
                    num_classes = state_dict["net.5.weight"].shape[0] if "net.5.weight" in state_dict else len(PERSONA_LABELS)

                if not self.feat_cols:
                    try:
                        base_ckpt = torch.load(_find_file("playstyle_classifier.pt"), map_location="cpu")
                        if isinstance(base_ckpt, dict):
                            self.feat_cols = base_ckpt.get("feat_cols")
                    except Exception:
                        pass
                
                self.model = PlaystyleClassifier(
                    input_dim=input_dim,
                    hidden_dim=hidden_dim,
                    num_classes=num_classes
                )
                self.model.load_state_dict(state_dict)
                self.model.eval()
        except Exception as e:
            print(f"[Predictor] Warning: could not load model or scaler: {e}")
            self.model = None
            self.scaler = None

    def predict(self, match_data: dict) -> dict:
        """
        Extract features and predict playstyle persona from a match dict.
        Returns a rich result dict containing label, confidence, probabilities, and profile.
        """
        try:
            feats = extract_match_features(match_data)
        except Exception as e:
            print(f"[Predictor] Error extracting features: {e}")
            feats = {}

        # Fallback if model/scaler not ready
        if self.model is None or self.scaler is None or not self.feat_cols:
            return self._heuristic_fallback(feats, match_data)

        try:
            # Build feature vector according to trained column ordering
            x_vec = np.zeros((1, len(self.feat_cols)), dtype=np.float32)
            for j, col in enumerate(self.feat_cols):
                val = feats.get(col, 0.0)
                if val is None or np.isnan(val) or np.isinf(val):
                    val = 0.0
                x_vec[0, j] = float(val)

            # Scale and infer
            x_scaled = self.scaler.transform(x_vec)
            x_tensor = torch.tensor(x_scaled, dtype=torch.float32)

            with torch.no_grad():
                logits = self.model(x_tensor)
                probs = torch.softmax(logits, dim=-1).squeeze(0).numpy()

            pred_idx = int(np.argmax(probs))
            predicted_persona = PERSONA_LABELS[pred_idx]
            confidence = float(probs[pred_idx])

            prob_dict = {
                label: round(float(probs[i]), 4)
                for i, label in enumerate(PERSONA_LABELS)
            }

            profile = PERSONA_PROFILES.get(predicted_persona, PERSONA_PROFILES["Optimal"])

            return {
                "persona": predicted_persona,
                "confidence": round(confidence, 4),
                "confidence_pct": round(confidence * 100, 1),
                "probabilities": prob_dict,
                "title": profile["title"],
                "description": profile["description"],
                "badge_color": profile["badge_color"],
                "icon": profile["icon"],
                "features": feats,
                "key_stats": {
                    "counter_rate": round(feats.get("counter_play_rate", 0.0) * 100, 1),
                    "damage_trade_ratio": round(feats.get("damage_trade_ratio", 1.0), 2),
                    "action_entropy": round(feats.get("action_entropy", 0.0), 2),
                    "avg_power": round(feats.get("avg_power_reserve", 0.0), 1),
                    "avg_xp": round(feats.get("avg_xp_reserve", 0.0), 1),
                    "miss_rate": round(feats.get("miss_rate", 0.0) * 100, 1),
                }
            }

        except Exception as e:
            print(f"[Predictor] Inference error: {e}")
            return self._heuristic_fallback(feats, match_data)

    def _heuristic_fallback(self, feats: dict, match_data: dict) -> dict:
        """Rule-based estimate if neural network is unavailable."""
        c_rate = feats.get("counter_play_rate", 0.0)
        avg_power = feats.get("avg_power_reserve", 20.0)
        entropy = feats.get("action_entropy", 1.5)
        heal_pct = feats.get("heal_avg_hp_pct_trigger", 0.0)

        if entropy > 2.2:
            persona = "Random"
        elif c_rate > 0.6 and heal_pct > 0.4:
            persona = "Defensive"
        elif avg_power > 45 and c_rate > 0.4:
            persona = "Optimal"
        else:
            persona = "Aggressive"

        profile = PERSONA_PROFILES.get(persona, PERSONA_PROFILES["Aggressive"])
        return {
            "persona": persona,
            "confidence": 0.75,
            "confidence_pct": 75.0,
            "probabilities": {persona: 0.75},
            "title": profile["title"],
            "description": profile["description"],
            "badge_color": profile["badge_color"],
            "icon": profile["icon"],
            "features": feats,
            "key_stats": {
                "counter_rate": round(c_rate * 100, 1),
                "damage_trade_ratio": round(feats.get("damage_trade_ratio", 1.0), 2),
                "action_entropy": round(entropy, 2),
                "avg_power": round(avg_power, 1),
                "avg_xp": round(feats.get("avg_xp_reserve", 0.0), 1),
                "miss_rate": round(feats.get("miss_rate", 0.0) * 100, 1),
            }
        }

    def predict_fighting_style(
        self,
        actions_or_match: Any = None,
        aggression_level: Optional[float] = None,
        counter_play_rate: Optional[float] = None,
        heal_hp_threshold: Optional[float] = None,
        decision_speed_ms: Optional[float] = None,
    ) -> dict:
        """
        Interactive fighting style prediction conforming directly to Section 9 of
        train_and_predict_playstyle.ipynb.
        """
        import random
        # 1. If actions_or_match is a full match dictionary
        if isinstance(actions_or_match, dict) and "turns" in actions_or_match:
            match_dict = actions_or_match
        # 2. If actions_or_match is a list of action names
        elif isinstance(actions_or_match, list) and len(actions_or_match) > 0:
            turns = []
            hero_hp = 110
            power = 50
            for i, act in enumerate(actions_or_match, 1):
                rt = decision_speed_ms if decision_speed_ms is not None else random.randint(1000, 2000)
                turns.append({
                    "turn_number": i,
                    "action_chosen": act,
                    "player_hp_before": hero_hp,
                    "player_power_before": power,
                    "player_xp_before": 50,
                    "damage_dealt": 25 if "Fire" in act else 14,
                    "damage_taken": 12,
                    "hit_success": True,
                    "action_matched_counter": (counter_play_rate is not None and random.random() < counter_play_rate),
                    "time_taken_to_decide": rt
                })
                if "Heal" in act: hero_hp = min(110, hero_hp + 30)
                elif "Rest" in act: power = min(100, power + 35)
            match_dict = {"summary": {"hero_class": "Wanderer Magician", "outcome": "win"}, "turns": turns}
        else:
            # 3. Build synthetic profile from high-level tactical traits
            agg = float(aggression_level if aggression_level is not None else 0.5)
            c_rate = float(counter_play_rate if counter_play_rate is not None else 0.4)
            h_thresh = float(heal_hp_threshold if heal_hp_threshold is not None else 0.35)
            speed = float(decision_speed_ms if decision_speed_ms is not None else 1500.0)

            turns = []
            for turn_no in range(1, 15):
                r = random.random()
                if r < agg * 0.6:
                    act = random.choice(["Fireball", "Fire Spell"])
                elif r < agg * 0.8:
                    act = "Quick Slash"
                elif random.random() < c_rate:
                    act = "Water Arrow"
                elif random.random() < 0.2:
                    act = "Rest & Recharge"
                else:
                    act = "Heal"

                turns.append({
                    "turn_number": turn_no,
                    "action_chosen": act,
                    "player_hp_before": 110 * (h_thresh if act == "Heal" else 0.8),
                    "player_power_before": 60 if agg < 0.6 else 20,
                    "player_xp_before": 60,
                    "damage_dealt": 25 if "Fire" in act else 12,
                    "damage_taken": 10 if random.random() < c_rate else 22,
                    "hit_success": True,
                    "action_matched_counter": (random.random() < c_rate),
                    "time_taken_to_decide": speed + random.randint(-150, 150)
                })
            match_dict = {"summary": {"hero_class": "Wanderer Magician", "outcome": "win"}, "turns": turns}

        res = self.predict(match_dict)
        res["model_source"] = NOTEBOOK_SOURCE
        res["global_architecture"] = "PlaystyleClassifier (MLP 49->32->32->4)"
        profile = PERSONA_PROFILES.get(res["persona"], PERSONA_PROFILES["Aggressive"])
        res["badge_color_hex"] = profile.get("badge_color_hex", "#a855f7")
        res["key_traits"] = profile.get("key_traits", [])
        return res

_GLOBAL_PREDICTOR = None

def get_predictor() -> PlaystylePredictor:
    global _GLOBAL_PREDICTOR
    if _GLOBAL_PREDICTOR is None:
        _GLOBAL_PREDICTOR = PlaystylePredictor()
    return _GLOBAL_PREDICTOR

def predict_match(match_data: dict) -> dict:
    """Direct helper to predict playstyle for a match dictionary."""
    return get_predictor().predict(match_data)

def predict_fighting_style(**kwargs) -> dict:
    """Interactive fighting style prediction conforming directly to Section 9 of the notebook."""
    return get_predictor().predict_fighting_style(**kwargs)
