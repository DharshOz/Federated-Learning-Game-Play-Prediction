"""
Arcane Clash — Model & Machine Learning Package.
Provides PyTorch playstyle classification, feature extraction, real-time inference, and Federated Learning (FedAvg + DP).
"""

from .model import PlaystyleClassifier, build_model, PERSONA_LABELS, LABEL_TO_IDX, IDX_TO_LABEL
from .extract_features import extract_match_features
from .predictor import PlaystylePredictor, get_predictor, predict_match
from .federated_engine import FederatedCoordinator, get_fl_coordinator

__all__ = [
    "PlaystyleClassifier",
    "build_model",
    "PERSONA_LABELS",
    "LABEL_TO_IDX",
    "IDX_TO_LABEL",
    "extract_match_features",
    "PlaystylePredictor",
    "get_predictor",
    "predict_match",
    "FederatedCoordinator",
    "get_fl_coordinator",
]
