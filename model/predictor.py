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

MODEL_PATH  = _find_file("playstyle_classifier.pt")
SCALER_PATH = _find_file("feature_scaler.joblib")

# Archetype metadata for rich UI and dashboard display
PERSONA_PROFILES = {
    "Aggressive": {
        "title": "Relentless Berserker",
        "badge_color": (255, 75, 90),
        "description": "Favors immediate high-damage spells and relentless pressure, delaying healing until critical health.",
        "icon": "⚔️"
    },
    "Defensive": {
        "title": "Tactical Guardian",
        "badge_color": (46, 213, 115),
        "description": "Anticipates boss telegraphs with precise soft-counters and maintains high health reserves via proactive recovery.",
        "icon": "🛡️"
    },
    "Optimal": {
        "title": "Grand Strategist",
        "badge_color": (155, 89, 182),
        "description": "Methodically balances resource thresholds (XP>80, Power>50) before unleashing high-value bursts and tactical counters.",
        "icon": "⚡"
    },
    "Random": {
        "title": "Wildcard Sorcerer",
        "badge_color": (255, 165, 2),
        "description": "Exhibits unpredictable spell variety and high action entropy without adhering to rigid tactical loops.",
        "icon": "🎲"
    }
}

class PlaystylePredictor:
    """Singleton/Cached predictor that evaluates completed matches."""

    def __init__(self, model_path=None, scaler_path=None):
        self.model_path = model_path or _find_file("playstyle_classifier.pt")
        self.scaler_path = scaler_path or _find_file("feature_scaler.joblib")
        self.model = None
        self.scaler = None
        self.feat_cols = None
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.scaler_path):
                self.scaler = joblib.load(self.scaler_path)
            
            if os.path.exists(self.model_path):
                ckpt = torch.load(self.model_path, map_location="cpu")
                input_dim = ckpt["input_dim"]
                hidden_dim = ckpt.get("hidden_dim", 32)
                num_classes = ckpt.get("num_classes", len(PERSONA_LABELS))
                self.feat_cols = ckpt.get("feat_cols")
                
                self.model = PlaystyleClassifier(
                    input_dim=input_dim,
                    hidden_dim=hidden_dim,
                    num_classes=num_classes
                )
                self.model.load_state_dict(ckpt["model_state_dict"])
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

_GLOBAL_PREDICTOR = None

def get_predictor() -> PlaystylePredictor:
    global _GLOBAL_PREDICTOR
    if _GLOBAL_PREDICTOR is None:
        _GLOBAL_PREDICTOR = PlaystylePredictor()
    return _GLOBAL_PREDICTOR

def predict_match(match_data: dict) -> dict:
    """Direct helper to predict playstyle for a match dictionary."""
    return get_predictor().predict(match_data)
