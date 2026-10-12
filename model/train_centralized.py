"""
train_centralized.py — Centralized baseline training for Arcane Clash Playstyle Classifier.

Workflow:
  1. Generate bot-persona match data (runs persona_bots.py if needed)
  2. Build feature dataset for all bot matches
  3. 70/15/15 stratified train/val/test split
  4. Standardize features (scaler fit on train only)
  5. Train PlaystyleClassifier with CrossEntropyLoss + Adam + early stopping
  6. Evaluate: test accuracy, confusion matrix heatmap, per-class F1
  7. Save model checkpoint + fitted scaler (both reused in future federated phase)
  8. Run trained model on real human match features → compare predicted labels vs
     cluster_id pseudo-labels using Adjusted Rand Index (ARI) as sanity check
  9. RandomForest feature importance check (leakage detector)

Usage:
    python train_centralized.py
    python train_centralized.py --epochs 100 --hidden-dim 64 --batch-size 32
    python train_centralized.py --dry-run   # quick smoke test (5 bot matches/persona, 10 epochs)
"""

import os
import sys
import json
import argparse
import warnings
import random
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # headless safe
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    classification_report, confusion_matrix, adjusted_rand_score
)
from sklearn.ensemble import RandomForestClassifier
import joblib

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE_DIR)

from extract_features import build_feature_dataset, load_all_matches
from model import PlaystyleClassifier, build_model, LABEL_TO_IDX, IDX_TO_LABEL, PERSONA_LABELS
from cluster_labels import run_clustering, is_bot_match, get_feature_columns

warnings.filterwarnings("ignore", category=FutureWarning)

# ─── Constants ────────────────────────────────────────────────────────────────
SEED = 42
LOGS_DIR         = os.path.join(_BASE_DIR, "logs")
MODEL_SAVE_PATH  = os.path.join(_BASE_DIR, "playstyle_classifier.pt")
SCALER_SAVE_PATH = os.path.join(_BASE_DIR, "feature_scaler.joblib")
CM_SAVE_PATH     = os.path.join(_BASE_DIR, "confusion_matrix.png")
LOSS_SAVE_PATH   = os.path.join(_BASE_DIR, "training_curves.png")
CLUSTER_CSV_PATH = os.path.join(_BASE_DIR, "cluster_assignments.csv")

LABEL_COL    = "persona_label"
OUTCOME_COL  = "outcome_won"

# ─── Seeds ────────────────────────────────────────────────────────────────────
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_model_feature_columns(df: pd.DataFrame) -> list:
    """Return list of numeric feature columns to feed into the model."""
    skip = set()
    for c in df.columns:
        if c.startswith("_") or c == OUTCOME_COL or c == LABEL_COL or c == "cluster_id":
            skip.add(c)
    return [c for c in df.columns if c not in skip]


def load_bot_dataset(logs_dir: str) -> pd.DataFrame:
    """Load all bot-persona match logs and extract features + persona labels."""
    raw_matches = load_all_matches(logs_dir)
    bot_matches = [m for m in raw_matches if is_bot_match(m.get("summary", {}).get("player_id", ""))]

    if not bot_matches:
        raise FileNotFoundError(
            "No bot match logs found. Run persona_bots.py first:\n"
            "  python persona_bots.py --matches 100"
        )

    from extract_features import extract_match_features, add_bigram_features

    feature_dicts = [extract_match_features(m) for m in bot_matches]
    for fd, m in zip(feature_dicts, bot_matches):
        fd["_source_file"] = m.get("_source_file", "")
        fd["_player_id"]   = m["summary"].get("player_id", "")
        fd["_match_id"]    = m["summary"].get("match_id",  "")
        # Attach persona label (stored in summary.persona_label by persona_bots.py)
        fd["persona_label"] = m["summary"].get("persona_label", "")

    all_turns = [m.get("turns", []) for m in bot_matches]
    add_bigram_features(feature_dicts, all_turns)

    return pd.DataFrame(feature_dicts)


def load_real_dataset(logs_dir: str, bot_bigram_cols: list) -> pd.DataFrame:
    """Load real (human) match logs and extract features with the same bigram columns."""
    raw_matches = load_all_matches(logs_dir)
    real_matches = [m for m in raw_matches if not is_bot_match(m.get("summary", {}).get("player_id", ""))]

    if not real_matches:
        return pd.DataFrame()

    from extract_features import extract_match_features, add_bigram_features

    feature_dicts = [extract_match_features(m) for m in real_matches]
    for fd, m in zip(feature_dicts, real_matches):
        fd["_source_file"] = m.get("_source_file", "")
        fd["_player_id"]   = m["summary"].get("player_id", "")
        fd["_match_id"]    = m["summary"].get("match_id",  "")

    all_turns = [m.get("turns", []) for m in real_matches]
    # Re-use the SAME bigram columns as bot dataset (consistent columns)
    add_bigram_features(feature_dicts, all_turns, top_bigram_cols=bot_bigram_cols)

    return pd.DataFrame(feature_dicts)


# ─── Training loop ────────────────────────────────────────────────────────────

def train_model(
    model: PlaystyleClassifier,
    train_loader: DataLoader,
    val_loader:   DataLoader,
    n_epochs:     int = 150,
    lr:           float = 1e-3,
    patience:     int = 20,
    device:       str = "cpu",
) -> dict:
    """
    Train PlaystyleClassifier with early stopping on validation loss.
    Returns history dict with train/val loss and accuracy per epoch.
    """
    model = model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=30, gamma=0.5)

    history = {"train_loss": [], "val_loss": [], "train_acc": [], "val_acc": []}
    best_val_loss = float("inf")
    patience_counter = 0
    best_state = None

    print(f"\n{'='*60}")
    print(f"Training  device={device}  epochs={n_epochs}  patience={patience}")
    print(f"{'='*60}")

    for epoch in range(1, n_epochs + 1):
        # ── Train ──────────────────────────────────────────────────────────────
        model.train()
        train_loss = train_correct = train_total = 0
        for X_batch, y_batch in train_loader:
            X_batch, y_batch = X_batch.to(device), y_batch.to(device)
            optimizer.zero_grad()
            logits = model(X_batch)
            loss = criterion(logits, y_batch)
            loss.backward()
            optimizer.step()
            train_loss    += loss.item() * len(y_batch)
            train_correct += (logits.argmax(1) == y_batch).sum().item()
            train_total   += len(y_batch)

        # ── Validate ───────────────────────────────────────────────────────────
        model.eval()
        val_loss = val_correct = val_total = 0
        with torch.no_grad():
            for X_batch, y_batch in val_loader:
                X_batch, y_batch = X_batch.to(device), y_batch.to(device)
                logits = model(X_batch)
                loss = criterion(logits, y_batch)
                val_loss    += loss.item() * len(y_batch)
                val_correct += (logits.argmax(1) == y_batch).sum().item()
                val_total   += len(y_batch)

        t_loss = train_loss / train_total
        v_loss = val_loss   / val_total
        t_acc  = train_correct / train_total
        v_acc  = val_correct   / val_total

        history["train_loss"].append(t_loss)
        history["val_loss"].append(v_loss)
        history["train_acc"].append(t_acc)
        history["val_acc"].append(v_acc)

        scheduler.step()

        if epoch % 10 == 0 or epoch == 1:
            print(f"  Epoch {epoch:4d}  "
                  f"train_loss={t_loss:.4f}  val_loss={v_loss:.4f}  "
                  f"train_acc={t_acc:.3f}  val_acc={v_acc:.3f}")

        # Early stopping
        if v_loss < best_val_loss - 1e-5:
            best_val_loss = v_loss
            patience_counter = 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            patience_counter += 1
            if patience_counter >= patience:
                print(f"  Early stopping at epoch {epoch} (patience={patience})")
                break

    # Restore best weights
    if best_state:
        model.load_state_dict(best_state)

    return history


# ─── Plotting ─────────────────────────────────────────────────────────────────

def plot_training_curves(history: dict, save_path: str):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    epochs = range(1, len(history["train_loss"]) + 1)

    axes[0].plot(epochs, history["train_loss"], label="Train Loss", color="#5B8DB8")
    axes[0].plot(epochs, history["val_loss"],   label="Val Loss",   color="#E07B54")
    axes[0].set_title("Loss Curves")
    axes[0].set_xlabel("Epoch"); axes[0].set_ylabel("Loss")
    axes[0].legend(); axes[0].grid(alpha=0.3)

    axes[1].plot(epochs, [a * 100 for a in history["train_acc"]], label="Train Acc", color="#5B8DB8")
    axes[1].plot(epochs, [a * 100 for a in history["val_acc"]],   label="Val Acc",   color="#E07B54")
    axes[1].set_title("Accuracy Curves")
    axes[1].set_xlabel("Epoch"); axes[1].set_ylabel("Accuracy (%)")
    axes[1].yaxis.set_major_formatter(mticker.PercentFormatter(xmax=100))
    axes[1].legend(); axes[1].grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Training curves saved: {save_path}")


def plot_confusion_matrix(cm: np.ndarray, labels: list, save_path: str, test_acc: float):
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(cm, interpolation="nearest", cmap="Blues")
    plt.colorbar(im, ax=ax)
    ax.set(
        xticks=np.arange(len(labels)),
        yticks=np.arange(len(labels)),
        xticklabels=labels, yticklabels=labels,
        title=f"Confusion Matrix  (test acc={test_acc:.1%})",
        ylabel="True Label", xlabel="Predicted Label",
    )
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right", fontsize=9)

    thresh = cm.max() / 2.0
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, format(cm[i, j], "d"),
                    ha="center", va="center",
                    color="white" if cm[i, j] > thresh else "black", fontsize=10)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Confusion matrix saved: {save_path}")


# ─── Leakage check ────────────────────────────────────────────────────────────

def check_feature_importance(
    X_train: np.ndarray,
    y_train: np.ndarray,
    feat_cols: list,
    top_n: int = 10,
    nn_test_acc: float = None,
) -> dict:
    """Train RandomForestClassifier and report feature importances as a leakage check."""
    print(f"\n{'='*60}")
    print("RandomForest Feature Importance (leakage sanity check)")
    print(f"{'='*60}")

    rf = RandomForestClassifier(n_estimators=300, random_state=SEED, n_jobs=-1)
    rf.fit(X_train, y_train)
    importances = rf.feature_importances_
    indices = np.argsort(importances)[::-1]

    print(f"\nTop {top_n} features by RandomForest importance:")
    top_feat_names = []
    top_feat_vals  = []
    for rank, idx in enumerate(indices[:top_n], 1):
        name = feat_cols[idx]
        imp  = importances[idx]
        top_feat_names.append(name)
        top_feat_vals.append(imp)
        print(f"  {rank:2d}. {name:45s}  importance={imp:.4f}")

    rf_test_acc = rf.score(X_train, y_train)

    # Leakage warning
    if nn_test_acc is not None and nn_test_acc > 0.98:
        top_imp_feat = feat_cols[indices[0]]
        if top_feat_vals[0] > 0.40:
            print(f"\n[WARNING] LEAKAGE WARNING: NN test accuracy={nn_test_acc:.1%} is suspiciously high.")
            print(f"  Top RF feature '{top_imp_feat}' captures {top_feat_vals[0]:.1%} of importance.")
            print("  Investigate if persona_label leaked into features or if bot strategies are trivially separable.")
        else:
            print(f"\n[OK] Accuracy={nn_test_acc:.1%} is high but feature importance is distributed. Looks clean.")
    else:
        print(f"\n[OK] RF train accuracy: {rf_test_acc:.1%} -- features look meaningful.")

    return {
        "rf_model":        rf,
        "top_feat_names":  top_feat_names,
        "top_feat_values": top_feat_vals,
        "all_importances": dict(zip(feat_cols, importances.tolist())),
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(args):
    t0 = time.time()

    # ── Step 0: Generate bot data if needed ───────────────────────────────────
    n_bot_matches = 5 if args.dry_run else args.bot_matches
    print(f"\n{'='*60}")
    print("Step 0: Generating bot persona match logs")
    print(f"{'='*60}")
    try:
        from persona_bots import run_all_personas
        run_all_personas(n_matches=n_bot_matches)
    except Exception as e:
        print(f"[WARNING] Could not run persona_bots: {e}")
        print("  Assuming bot match logs already exist under logs/")

    # ── Step 1: Load bot dataset ───────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("Step 1: Loading bot match features")
    print(f"{'='*60}")
    df_bot = load_bot_dataset(LOGS_DIR)

    # Filter to known personas
    df_bot = df_bot[df_bot[LABEL_COL].isin(PERSONA_LABELS)].copy()
    print(f"  Bot matches with valid persona label: {len(df_bot)}")
    print(f"  Per-persona counts:\n{df_bot[LABEL_COL].value_counts().to_string()}")

    if len(df_bot) < 12:
        raise ValueError(f"Not enough bot matches ({len(df_bot)}) to train. Run persona_bots.py first.")

    # Determine feature columns from bot dataset
    feat_cols = get_model_feature_columns(df_bot)

    # Identify bigram columns (to reuse for real matches later)
    bigram_cols = [c for c in feat_cols if c.startswith("action_bigram_")]

    print(f"\n  Total feature columns: {len(feat_cols)}")
    print(f"  Feature count ASSERTED: {len(feat_cols)}")
    assert len(feat_cols) > 0, "Feature column list is empty!"

    X = df_bot[feat_cols].fillna(0).values.astype(np.float32)
    y = np.array([LABEL_TO_IDX[p] for p in df_bot[LABEL_COL]])

    # ── Step 2: Train/val/test split (70/15/15 stratified) ────────────────────
    print(f"\n{'='*60}")
    print("Step 2: Stratified 70/15/15 split")
    print(f"{'='*60}")
    X_train, X_temp, y_train, y_temp = train_test_split(
        X, y, test_size=0.30, random_state=SEED, stratify=y
    )
    X_val, X_test, y_val, y_test = train_test_split(
        X_temp, y_temp, test_size=0.50, random_state=SEED, stratify=y_temp
    )
    print(f"  Train: {len(X_train)}  Val: {len(X_val)}  Test: {len(X_test)}")

    # ── Step 3: Standardize (fit on train only) ────────────────────────────────
    print(f"\n{'='*60}")
    print("Step 3: Feature standardization (fit on train)")
    print(f"{'='*60}")
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train).astype(np.float32)
    X_val_s   = scaler.transform(X_val).astype(np.float32)
    X_test_s  = scaler.transform(X_test).astype(np.float32)

    # Save fitted scaler (reused in federated phase)
    joblib.dump(scaler, SCALER_SAVE_PATH)
    print(f"  Scaler saved: {SCALER_SAVE_PATH}")

    # ── Step 4: Build DataLoaders ─────────────────────────────────────────────
    batch_size = args.batch_size
    train_ds = TensorDataset(torch.tensor(X_train_s), torch.tensor(y_train, dtype=torch.long))
    val_ds   = TensorDataset(torch.tensor(X_val_s),   torch.tensor(y_val,   dtype=torch.long))
    test_ds  = TensorDataset(torch.tensor(X_test_s),  torch.tensor(y_test,  dtype=torch.long))
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,  drop_last=False)
    val_loader   = DataLoader(val_ds,   batch_size=batch_size, shuffle=False)
    test_loader  = DataLoader(test_ds,  batch_size=batch_size, shuffle=False)

    # ── Step 5: Build model (input_dim from actual feature count) ─────────────
    print(f"\n{'='*60}")
    print("Step 5: Building PlaystyleClassifier")
    print(f"{'='*60}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model  = build_model(feat_cols, hidden_dim=args.hidden_dim)

    # ── Step 6: Train ─────────────────────────────────────────────────────────
    n_epochs  = 10 if args.dry_run else args.epochs
    patience  = 5  if args.dry_run else args.patience
    history   = train_model(
        model, train_loader, val_loader,
        n_epochs=n_epochs, lr=args.lr, patience=patience, device=device
    )
    plot_training_curves(history, LOSS_SAVE_PATH)

    # ── Step 7: Evaluate on test set ──────────────────────────────────────────
    print(f"\n{'='*60}")
    print("Step 7: Test set evaluation")
    print(f"{'='*60}")
    model.eval()
    all_preds, all_true = [], []
    with torch.no_grad():
        for X_batch, y_batch in test_loader:
            logits = model(X_batch.to(device))
            all_preds.extend(logits.argmax(1).cpu().numpy())
            all_true.extend(y_batch.numpy())

    all_preds = np.array(all_preds)
    all_true  = np.array(all_true)
    test_acc  = (all_preds == all_true).mean()

    print(f"\n  Test Accuracy: {test_acc:.4f} ({test_acc:.1%})")
    print(f"\n  Classification Report:")
    report = classification_report(
        all_true, all_preds,
        labels=list(range(len(PERSONA_LABELS))),
        target_names=PERSONA_LABELS,
        digits=4,
        zero_division=0
    )
    print(report)

    cm = confusion_matrix(all_true, all_preds, labels=list(range(len(PERSONA_LABELS))))
    plot_confusion_matrix(cm, PERSONA_LABELS, CM_SAVE_PATH, test_acc)

    # ── Step 8: Save model ────────────────────────────────────────────────────
    torch.save({
        "model_state_dict": model.state_dict(),
        "input_dim":        len(feat_cols),
        "hidden_dim":       args.hidden_dim,
        "num_classes":      len(PERSONA_LABELS),
        "feat_cols":        feat_cols,
        "persona_labels":   PERSONA_LABELS,
        "label_to_idx":     LABEL_TO_IDX,
    }, MODEL_SAVE_PATH)
    print(f"\n  Model checkpoint saved: {MODEL_SAVE_PATH}")

    # ── Step 9: RandomForest leakage check ────────────────────────────────────
    rf_results = check_feature_importance(
        X_train_s, y_train, feat_cols, top_n=10, nn_test_acc=test_acc
    )

    # ── Step 10: Run on real matches + ARI comparison ─────────────────────────
    print(f"\n{'='*60}")
    print("Step 10: Predict on real (human) matches + ARI vs cluster_id")
    print(f"{'='*60}")

    df_real = load_real_dataset(LOGS_DIR, bot_bigram_cols=bigram_cols)
    if df_real.empty:
        print("  No real match data found — skipping ARI comparison.")
        ari_score = None
    else:
        print(f"  Real matches loaded: {len(df_real)}")

        # Run clustering to get cluster_id pseudo-labels
        df_cluster = run_clustering(LOGS_DIR, out_csv=CLUSTER_CSV_PATH)
        if df_cluster.empty or "cluster_id" not in df_cluster.columns:
            print("  Clustering produced no results — skipping ARI.")
            ari_score = None
        else:
            # Align real match features with clustering results
            df_real_feats = df_real[feat_cols].fillna(0).values.astype(np.float32)
            X_real_s = scaler.transform(df_real_feats).astype(np.float32)
            X_real_t = torch.tensor(X_real_s)
            pred_indices = model.predict(X_real_t).numpy()

            # Merge predictions with cluster assignments on match_id
            pred_df = pd.DataFrame({
                "_match_id":    df_real["_match_id"].values,
                "nn_pred_class": pred_indices,
            })
            clust_df = df_cluster[["_match_id", "cluster_id"]].copy()
            merged = pred_df.merge(clust_df, on="_match_id", how="inner")

            if len(merged) == 0:
                print("  Could not align real predictions with cluster assignments -- skipping ARI.")
                ari_score = None
            else:
                ari_score = adjusted_rand_score(merged["cluster_id"], merged["nn_pred_class"])
                print(f"\n  Adjusted Rand Index (ARI): {ari_score:.4f}")
                print("  (0 = random agreement, 1 = perfect agreement)")
                if ari_score > 0.3:
                    print("  [OK] Neural network and k-means broadly agree on cluster structure.")
                elif ari_score > 0.0:
                    print("  [INFO] Weak agreement -- human play may span multiple archetypes per match.")
                else:
                    print("  [INFO] No agreement -- clustering and NN disagree (expected with very few real matches).")

                print(f"\n  Predicted class distribution on real matches:")
                for i, label in enumerate(PERSONA_LABELS):
                    count = (pred_indices == i).sum()
                    pct   = count / len(pred_indices) if len(pred_indices) > 0 else 0
                    print(f"    {label:12s}: {count:3d} matches ({pct:.1%})")

    # ── Final summary ─────────────────────────────────────────────────────────
    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print("TRAINING COMPLETE")
    print(f"{'='*60}")
    print(f"  Test accuracy         : {test_acc:.1%}")
    print(f"  Confusion matrix      : {CM_SAVE_PATH}")
    print(f"  Training curves       : {LOSS_SAVE_PATH}")
    print(f"  Model checkpoint      : {MODEL_SAVE_PATH}")
    print(f"  Scaler                : {SCALER_SAVE_PATH}")
    if ari_score is not None:
        print(f"  ARI (NN vs KMeans)    : {ari_score:.4f}")
    print(f"  Total time            : {elapsed:.1f}s")
    print(f"{'='*60}")

    return {
        "test_accuracy":    test_acc,
        "confusion_matrix": cm,
        "classification_report": report,
        "history":          history,
        "rf_results":       rf_results,
        "ari_score":        ari_score,
        "feat_cols":        feat_cols,
    }


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Centralized training for Arcane Clash Playstyle Classifier")
    parser.add_argument("--epochs",      type=int,   default=150,  help="Max training epochs")
    parser.add_argument("--patience",    type=int,   default=20,   help="Early stopping patience")
    parser.add_argument("--lr",          type=float, default=1e-3, help="Adam learning rate")
    parser.add_argument("--batch-size",  type=int,   default=32,   help="Mini-batch size")
    parser.add_argument("--hidden-dim",  type=int,   default=32,   help="Hidden layer width")
    parser.add_argument("--bot-matches", type=int,   default=100,  help="Bot matches per persona")
    parser.add_argument("--dry-run",     action="store_true",       help="Quick smoke test (5 matches, 10 epochs)")
    args = parser.parse_args()

    main(args)
