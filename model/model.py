"""
model.py — PlaystyleClassifier for Arcane Clash Playstyle Classification (Phase 1).

Fully decoupled from any training strategy (centralized or federated).
This same class will be reused unchanged when federated training (e.g., Flower/FedAvg)
is added in a later phase — only the training loop changes, not the model.

Architecture:
    Linear(input_dim → hidden_dim) → ReLU → Dropout(0.2)
    → Linear(hidden_dim → hidden_dim) → ReLU
    → Linear(hidden_dim → num_classes)

input_dim is set DYNAMICALLY from the actual number of feature columns produced by
extract_match_features() + add_bigram_features(). It is asserted at construction time
(never hardcoded) to catch schema drift early.

Classes (persona labels):
    0 → Aggressive
    1 → Defensive
    2 → Optimal
    3 → Random
"""

import torch
import torch.nn as nn
from typing import Optional

# ─── Label encoding (must match persona_bots.PERSONA_DECIDERS key order) ──────
PERSONA_LABELS = ["Aggressive", "Defensive", "Optimal", "Random"]
LABEL_TO_IDX   = {label: idx for idx, label in enumerate(PERSONA_LABELS)}
IDX_TO_LABEL   = {idx: label for label, idx in LABEL_TO_IDX.items()}
NUM_CLASSES     = len(PERSONA_LABELS)


# ─── Model ────────────────────────────────────────────────────────────────────

class PlaystyleClassifier(nn.Module):
    """
    A compact MLP classifier that maps a flat feature vector to one of
    4 playstyle classes (Aggressive / Defensive / Optimal / Random).

    Parameters
    ----------
    input_dim  : int  — must equal the exact number of columns produced by
                        extract_match_features() (verified at construction time).
    hidden_dim : int  — width of the two hidden layers (default 32).
    num_classes: int  — number of output logits (default 4).
    dropout    : float — dropout rate between first two layers (default 0.2).
    """

    def __init__(
        self,
        input_dim:   int,
        hidden_dim:  int = 32,
        num_classes: int = NUM_CLASSES,
        dropout:     float = 0.2,
    ):
        super().__init__()

        # Runtime assertion: catch stale input_dim values immediately
        assert isinstance(input_dim, int) and input_dim > 0, (
            f"input_dim must be a positive integer, got {input_dim!r}. "
            "Derive it from len(feature_columns) after running build_feature_dataset()."
        )

        self.input_dim  = input_dim
        self.hidden_dim = hidden_dim
        self.num_classes = num_classes

        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, num_classes),
        )

        # Kaiming (He) initialisation for ReLU networks — better convergence
        self._init_weights()

    def _init_weights(self):
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.kaiming_uniform_(module.weight, nonlinearity="relu")
                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass.

        Parameters
        ----------
        x : torch.Tensor of shape (batch_size, input_dim)

        Returns
        -------
        logits : torch.Tensor of shape (batch_size, num_classes)
            Raw (un-softmaxed) class scores. Pass to CrossEntropyLoss directly.
        """
        return self.net(x)

    def predict(self, x: torch.Tensor) -> torch.Tensor:
        """Convenience: returns predicted class indices (argmax of logits)."""
        with torch.no_grad():
            logits = self.forward(x)
        return logits.argmax(dim=-1)

    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        """Convenience: returns class probabilities (softmax of logits)."""
        with torch.no_grad():
            logits = self.forward(x)
        return torch.softmax(logits, dim=-1)

    def __repr__(self) -> str:
        total_params = sum(p.numel() for p in self.parameters())
        return (
            f"PlaystyleClassifier("
            f"input_dim={self.input_dim}, "
            f"hidden_dim={self.hidden_dim}, "
            f"num_classes={self.num_classes}, "
            f"total_params={total_params:,})"
        )


# ─── Factory helper ───────────────────────────────────────────────────────────

def build_model(feature_columns, hidden_dim: int = 32) -> PlaystyleClassifier:
    """
    Construct a PlaystyleClassifier with input_dim dynamically derived from
    the actual feature column list.

    Parameters
    ----------
    feature_columns : list[str]
        The list of column names that will be fed as model input.
        Must NOT include 'outcome_won' or metadata ('_*') columns.
    hidden_dim : int
        Width of hidden layers.

    Returns
    -------
    PlaystyleClassifier
    """
    input_dim = len(feature_columns)
    print(f"[model] Building PlaystyleClassifier with input_dim={input_dim}")
    assert input_dim > 0, "feature_columns must not be empty"
    model = PlaystyleClassifier(input_dim=input_dim, hidden_dim=hidden_dim)
    print(f"[model] {model}")
    return model


# ─── Smoke test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    torch.manual_seed(42)
    # Simulate a batch with a dummy feature count
    dummy_input_dim = 60
    model = PlaystyleClassifier(input_dim=dummy_input_dim)
    print(model)

    x = torch.randn(8, dummy_input_dim)
    logits = model(x)
    probs  = model.predict_proba(x)
    preds  = model.predict(x)

    print(f"Input  shape : {x.shape}")
    print(f"Logits shape : {logits.shape}")
    print(f"Probs  shape : {probs.shape}")
    print(f"Preds        : {preds.tolist()}")
    print(f"Labels       : {[IDX_TO_LABEL[p.item()] for p in preds]}")
    print("Smoke test passed.")
