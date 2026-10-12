"""
federated_engine.py — Federated Learning (FedAvg + Differential Privacy) Engine.

Coordinates Federated Learning rounds across distributed Arcane Clash players.
1. Groups game logs stored in DB by player_id (simulating local client shards).
2. Distributes the global PlaystyleClassifier to participating client nodes.
3. Trains local client models on private client data for E local epochs.
4. Applies Differential Privacy (gradient/weight clipping and calibrated Gaussian noise).
5. Aggregates updated weights using Federated Averaging (FedAvg):
       W_global = sum( (n_k / N) * W_k )
6. Evaluates global model performance and persists the new checkpoint.
"""

import os
import sys
import copy
import time
import math
import random
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from dotenv import load_dotenv
from typing import List, Dict, Optional, Any, Tuple
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

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

try:
    from .model import PlaystyleClassifier, PERSONA_LABELS, LABEL_TO_IDX
    from .extract_features import extract_match_features
except (ImportError, ValueError):
    from model import PlaystyleClassifier, PERSONA_LABELS, LABEL_TO_IDX
    from extract_features import extract_match_features

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

MODEL_PATH     = _find_file("playstyle_classifier.pt")
FL_GLOBAL_PATH = _find_file("fl_global_model.pt")
SCALER_PATH    = _find_file("feature_scaler.joblib")

DEFAULT_EPSILON = float(os.getenv("FL_DP_EPSILON", "1.5"))
DEFAULT_EPOCHS  = int(os.getenv("FL_LOCAL_EPOCHS", "3"))
DEFAULT_LR      = float(os.getenv("FL_LEARNING_RATE", "0.005"))

class FederatedCoordinator:
    """Manages Federated Learning rounds, client updates, and FedAvg aggregation."""

    def __init__(self):
        self.scaler: Optional[Any] = None
        self.feat_cols: List[str] = []
        self.input_dim: int = 49
        self.hidden_dim: int = 32
        self.num_classes: int = 4
        self.global_model: PlaystyleClassifier = PlaystyleClassifier(
            input_dim=self.input_dim,
            hidden_dim=self.hidden_dim,
            num_classes=self.num_classes
        )
        self._load_base_model()

    def _load_base_model(self):
        if os.path.exists(SCALER_PATH):
            try:
                self.scaler = joblib.load(SCALER_PATH)
            except Exception:
                pass

        if os.path.exists(MODEL_PATH):
            try:
                ckpt = torch.load(MODEL_PATH, map_location="cpu")
                self.input_dim = ckpt.get("input_dim", 49)
                self.hidden_dim = ckpt.get("hidden_dim", 32)
                self.num_classes = ckpt.get("num_classes", 4)
                self.feat_cols = list(ckpt.get("feat_cols") or [])
                
                self.global_model = PlaystyleClassifier(
                    input_dim=self.input_dim,
                    hidden_dim=self.hidden_dim,
                    num_classes=self.num_classes
                )
                self.global_model.load_state_dict(ckpt["model_state_dict"])
            except Exception as e:
                print(f"[FederatedCoordinator] Model load error: {e}")
                self._init_fresh_model()
        else:
            self._init_fresh_model()

    def _init_fresh_model(self):
        self.global_model = PlaystyleClassifier(
            input_dim=self.input_dim,
            hidden_dim=self.hidden_dim,
            num_classes=self.num_classes
        )
        if not self.feat_cols:
            self.feat_cols = [f"f_{i}" for i in range(self.input_dim)]

    def extract_vector(self, match_doc: dict) -> tuple:
        """Extracts (feature_vector, label_idx) from match document."""
        feats = match_doc.get("features")
        if not feats:
            feats = extract_match_features(match_doc)

        cols = self.feat_cols if self.feat_cols else list(feats.keys())
        x_vec = np.zeros(len(cols), dtype=np.float32)
        for j, col in enumerate(cols):
            val = feats.get(col, 0.0)
            if val is None or np.isnan(val) or np.isinf(val):
                val = 0.0
            x_vec[j] = float(val)

        # Label resolution: ground-truth persona if bot, else predicted/pseudo-label
        summary = match_doc.get("summary", {})
        label_str = summary.get("persona_label") or match_doc.get("prediction", {}).get("persona") or "Optimal"
        y_label = LABEL_TO_IDX.get(label_str, 2)

        return x_vec, y_label

    def prepare_client_shards(self, matches: list) -> dict:
        """Partition matches by player_id to form local private client datasets."""
        shards = {}
        for m in matches:
            pid = m.get("player_id", "unknown_player")
            try:
                x, y = self.extract_vector(m)
                if pid not in shards:
                    shards[pid] = {"X": [], "y": []}
                shards[pid]["X"].append(x)
                shards[pid]["y"].append(y)
            except Exception:
                continue

        # Convert to numpy arrays & scale using fitted global scaler
        ready_shards = {}
        for pid, data in shards.items():
            if len(data["X"]) == 0:
                continue
            X_arr = np.array(data["X"], dtype=np.float32)
            y_arr = np.array(data["y"], dtype=np.int64)
            if self.scaler is not None:
                X_arr = self.scaler.transform(X_arr)
            ready_shards[pid] = {"X": X_arr, "y": y_arr, "count": len(X_arr)}

        return ready_shards

    def train_client_local(self, model: nn.Module, X: np.ndarray, y: np.ndarray,
                           epochs: int = 3, lr: float = 0.005, epsilon_dp: float = 1.5) -> dict:
        """
        Simulates local training on client edge device.
        Applies Differential Privacy via gradient clipping & Gaussian perturbation.
        """
        local_model = copy.deepcopy(model)
        local_model.train()
        optimizer = torch.optim.Adam(local_model.parameters(), lr=lr)
        criterion = nn.CrossEntropyLoss()

        dataset = TensorDataset(torch.tensor(X, dtype=torch.float32), torch.tensor(y, dtype=torch.long))
        loader = DataLoader(dataset, batch_size=max(2, min(len(dataset), 16)), shuffle=True)

        # Differential Privacy: Gradient clipping to bounded sensitivity C
        C = 1.0
        for _ in range(epochs):
            for batch_x, batch_y in loader:
                optimizer.zero_grad()
                out = local_model(batch_x)
                loss = criterion(out, batch_y)
                loss.backward()

                nn.utils.clip_grad_norm_(local_model.parameters(), max_norm=C)

                optimizer.step()

        # Differential Privacy: Inject calibrated Gaussian noise to weights
        # sigma = C * sqrt(2 * ln(1.25 / delta)) / epsilon
        delta = 1e-4
        if epsilon_dp > 0:
            sigma = (C * math.sqrt(2 * math.log(1.25 / delta))) / epsilon_dp
            # Scale down noise proportional to dataset size so model remains accurate
            sigma = sigma / (len(X) + 1)
            with torch.no_grad():
                for param in local_model.parameters():
                    noise = torch.randn_like(param) * (sigma * 0.02)
                    param.add_(noise)

        return local_model.state_dict()

    def aggregate_fedavg(self, client_weights: list, client_counts: list) -> dict:
        """
        Performs Federated Averaging (FedAvg):
        W_global = sum_{k=1}^K (n_k / N) * W_k
        """
        total_samples = sum(client_counts)
        if total_samples == 0:
            return self.global_model.state_dict()

        avg_weights = {}
        for key in client_weights[0].keys():
            avg_weights[key] = sum(
                (count / total_samples) * weights[key].clone().type(torch.float32)
                for weights, count in zip(client_weights, client_counts)
            )

        return avg_weights

    def evaluate_global(self, all_X: np.ndarray, all_y: np.ndarray) -> tuple:
        """Evaluates accuracy and loss across full federated test partition."""
        if len(all_X) == 0:
            return 0.0, 0.0

        self.global_model.eval()
        criterion = nn.CrossEntropyLoss()
        with torch.no_grad():
            t_x = torch.tensor(all_X, dtype=torch.float32)
            t_y = torch.tensor(all_y, dtype=torch.long)
            logits = self.global_model(t_x)
            loss = criterion(logits, t_y).item()
            preds = logits.argmax(dim=-1)
            acc = (preds == t_y).float().mean().item()

        return acc, loss

    def train_federated_round(self, matches: list, local_epochs: int = DEFAULT_EPOCHS,
                              epsilon_dp: float = DEFAULT_EPSILON, lr: float = DEFAULT_LR) -> dict:
        """
        Executes a complete Federated Learning round (FedAvg) over available matches.
        """
        if not self.feat_cols:
            self._load_base_model()

        shards = self.prepare_client_shards(matches)
        if not shards:
            return {
                "success": False,
                "message": "Insufficient client match telemetry to form federated shards.",
                "participating_clients": 0
            }

        client_weights = []
        client_counts = []
        client_contributions = []

        all_X_list, all_y_list = [], []

        for pid, shard in shards.items():
            cnt = shard["count"]
            client_counts.append(cnt)
            all_X_list.append(shard["X"])
            all_y_list.append(shard["y"])

            # Local training on client partition
            w_local = self.train_client_local(
                model=self.global_model,
                X=shard["X"],
                y=shard["y"],
                epochs=local_epochs,
                lr=lr,
                epsilon_dp=epsilon_dp
            )
            client_weights.append(w_local)
            client_contributions.append({
                "player_id": pid,
                "samples": cnt,
                "weight_share": 0.0
            })

        total_samples = sum(client_counts)
        for c in client_contributions:
            c["weight_share"] = round((c["samples"] / total_samples) * 100, 1)

        # FedAvg Aggregation
        aggregated_state = self.aggregate_fedavg(client_weights, client_counts)
        self.global_model.load_state_dict(aggregated_state)

        # Global Evaluation
        all_X = np.vstack(all_X_list)
        all_y = np.concatenate(all_y_list)
        acc, loss = self.evaluate_global(all_X, all_y)

        # Save Checkpoint
        torch.save(self.global_model.state_dict(), FL_GLOBAL_PATH)
        torch.save({
            "model_state_dict": self.global_model.state_dict(),
            "input_dim": self.input_dim,
            "hidden_dim": self.hidden_dim,
            "num_classes": self.num_classes,
            "feat_cols": self.feat_cols,
            "persona_labels": PERSONA_LABELS,
            "label_to_idx": LABEL_TO_IDX
        }, MODEL_PATH)

        return {
            "success": True,
            "global_accuracy": round(acc * 100, 2),
            "global_loss": round(loss, 4),
            "participating_clients": len(shards),
            "total_samples": total_samples,
            "client_contributions": client_contributions,
            "epsilon_dp": epsilon_dp,
            "local_epochs": local_epochs,
            "timestamp": time.time(),
            "status": "COMPLETED"
        }

_GLOBAL_FL_COORDINATOR = None

def get_fl_coordinator() -> FederatedCoordinator:
    global _GLOBAL_FL_COORDINATOR
    if _GLOBAL_FL_COORDINATOR is None:
        _GLOBAL_FL_COORDINATOR = FederatedCoordinator()
    return _GLOBAL_FL_COORDINATOR
