"""
extract_features.py — Phase 1 Feature Extraction for Arcane Clash Playstyle Classifier.

Decoupled from any training strategy (centralized or federated).
The same extract_match_features() function will be reused unchanged in future federated phases.

Feature Groups:
  A — Action distribution (pct_<action>, action_entropy, opening_is_<action>)
  B — Resource management (avg/std/min of power & xp, floor events)
  C — Combat efficiency (damage dealt/taken, miss rate, risky spell miss rate)
  D — Threat response / counter-play (counter_play_rate, half-match breakdowns)
  E — Risk / clutch behavior (heal trigger hp%, clutch entropy, comeback_flag)
  F — Decision timing (avg/median/std/cv reaction time, slow_decision_rate)
  G — Status effect handling (uptime rate, turns-to-clear weakened)
  H — Sequence / transition patterns (bigrams, repeat rate, post-damage defense)
  I — Outcome (outcome_won — label only, EXCLUDED from model input features)
"""

import math
import numpy as np
from typing import Dict, Any, List, Optional

# ─── Constants ────────────────────────────────────────────────────────────────

KNOWN_ACTIONS: List[str] = [
    "Quick Slash",
    "Fireball",
    "Water Arrow",
    "Water Spell",
    "Fire Spell",
    "Heal",
    "Rest & Recharge",
]

# Canonical snake_case keys for feature names
_ACTION_KEYS: List[str] = [
    "quick_slash",
    "fireball",
    "water_arrow",
    "water_spell",
    "fire_spell",
    "heal",
    "rest_and_recharge",
]

# Map display label → snake_case key
_LABEL_TO_KEY: Dict[str, str] = {label: key for label, key in zip(KNOWN_ACTIONS, _ACTION_KEYS)}

# Starting HP per hero class (from game constants in game.py / entity.py)
HERO_MAX_HP: Dict[str, int] = {
    "Fire Wizard": 120,
    "Lightning Mage": 100,
    "Wanderer Magician": 110,
    "Wanderer": 110,   # alias used in some logs from game.py HEROES list
}
DEFAULT_MAX_HP = 110  # safe fallback for unknown hero classes

# Risky spells for miss rate sub-metric (Group C)
_RISKY_SPELLS = {"Fire Spell", "Fireball"}

# Threshold for "overextension" events (Group B)
_RESOURCE_FLOOR = 10

# "Slow" decision threshold in milliseconds (Group F)
_SLOW_DECISION_MS = 15_000

# HP fraction threshold for "clutch / desperate" state (Group E)
_CLUTCH_HP_PCT = 0.30

# Reactive caution: damage-taken threshold (Group H)
_REACTIVE_DMG_THRESHOLD = 20


# ─── Helper utilities ─────────────────────────────────────────────────────────

def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Division that returns `default` instead of raising ZeroDivisionError."""
    return numerator / denominator if denominator != 0 else default


def _shannon_entropy(counts: Dict[str, int]) -> float:
    """Shannon entropy (base-2) from a count dict. Returns 0.0 for empty / single-entry."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    probs = [c / total for c in counts.values() if c > 0]
    return float(-sum(p * math.log2(p) for p in probs))


# ─── Main extraction function ─────────────────────────────────────────────────

def extract_match_features(match_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract a flat dict of numeric features from a single match JSON.

    Parameters
    ----------
    match_json : dict
        Parsed match JSON conforming to the Arcane Clash log schema.
        Gracefully handles missing optional fields (combo_triggered,
        boss_phase_at_decision, boss_adaptive_weights_snapshot).

    Returns
    -------
    dict
        Flat dict with all feature groups A-H as numeric values, plus
        a separate key ``"outcome_won"`` (bool) that must NOT be fed
        into the model as a feature (Group I).
    """
    summary: Dict[str, Any] = match_json.get("summary", {})
    turns: List[Dict[str, Any]] = match_json.get("turns", [])

    hero_class: str = summary.get("hero_class", "")
    max_hp: int = HERO_MAX_HP.get(hero_class, DEFAULT_MAX_HP)
    n_turns = len(turns)
    total_turns: int = max(n_turns, 1)  # guard against 0-turn edge case

    feats: Dict[str, Any] = {}

    # ──────────────────────────────────────────────────────────────────────────
    # GROUP A — Action distribution
    # Recomputed from turns (not from summary.action_frequency_distribution)
    # to avoid relying on a field that may be stale or missing.
    # ──────────────────────────────────────────────────────────────────────────
    action_counts: Dict[str, int] = {k: 0 for k in _ACTION_KEYS}
    for t in turns:
        label = t.get("action_chosen", "")
        key = _LABEL_TO_KEY.get(label)
        if key:
            action_counts[key] += 1

    for key in _ACTION_KEYS:
        feats[f"pct_{key}"] = _safe_div(action_counts[key], n_turns)

    feats["action_entropy"] = _shannon_entropy(action_counts)

    # Opening action one-hot (turn 1)
    opening_turn = next((t for t in turns if t.get("turn_number") == 1), None)
    if opening_turn is None and turns:
        opening_turn = turns[0]
    opening_label = opening_turn.get("action_chosen", "") if opening_turn else ""
    opening_key = _LABEL_TO_KEY.get(opening_label, "")
    for key in _ACTION_KEYS:
        feats[f"opening_is_{key}"] = 1 if key == opening_key else 0

    # ──────────────────────────────────────────────────────────────────────────
    # GROUP B — Resource management
    # ──────────────────────────────────────────────────────────────────────────
    power_vals = [t.get("player_power_before", 0) for t in turns]
    xp_vals    = [t.get("player_xp_before",    0) for t in turns]

    feats["avg_power_reserve"] = float(np.mean(power_vals)) if power_vals else 0.0
    feats["avg_xp_reserve"]    = float(np.mean(xp_vals))    if xp_vals    else 0.0
    feats["power_reserve_std"] = float(np.std(power_vals))  if power_vals else 0.0
    feats["xp_reserve_std"]    = float(np.std(xp_vals))     if xp_vals    else 0.0
    feats["min_power_reached"] = float(min(power_vals)) if power_vals else 0.0
    feats["min_xp_reached"]    = float(min(xp_vals))    if xp_vals    else 0.0

    feats["resource_floor_events"] = sum(
        1 for t in turns
        if t.get("player_power_before", 0) < _RESOURCE_FLOOR
        or t.get("player_xp_before",    0) < _RESOURCE_FLOOR
    )

    # ──────────────────────────────────────────────────────────────────────────
    # GROUP C — Combat efficiency
    # ──────────────────────────────────────────────────────────────────────────
    total_dealt = sum(t.get("damage_dealt", 0) for t in turns)
    total_taken = sum(t.get("damage_taken", 0) for t in turns)

    feats["total_damage_dealt"] = float(total_dealt)
    feats["total_damage_taken"] = float(total_taken)
    feats["damage_trade_ratio"] = _safe_div(total_dealt, max(total_taken, 1))

    miss_count = sum(1 for t in turns if not t.get("hit_success", True))
    feats["miss_rate"] = _safe_div(miss_count, n_turns)

    risky_turns = [t for t in turns if t.get("action_chosen", "") in _RISKY_SPELLS]
    risky_misses = sum(1 for t in risky_turns if not t.get("hit_success", True))
    feats["miss_rate_by_risky_spell"] = _safe_div(risky_misses, max(len(risky_turns), 1))

    # ──────────────────────────────────────────────────────────────────────────
    # GROUP D — Threat response / counter-play
    # ──────────────────────────────────────────────────────────────────────────
    half = total_turns / 2.0
    first_half  = [t for t in turns if t.get("turn_number", 0) <= half]
    second_half = [t for t in turns if t.get("turn_number", 0) >  half]

    counter_total  = sum(1 for t in turns       if t.get("action_matched_counter", False))
    counter_first  = sum(1 for t in first_half  if t.get("action_matched_counter", False))
    counter_second = sum(1 for t in second_half if t.get("action_matched_counter", False))

    feats["counter_play_rate"]             = _safe_div(counter_total,  n_turns)
    feats["counter_play_rate_first_half"]  = _safe_div(counter_first,  max(len(first_half),  1))
    feats["counter_play_rate_second_half"] = _safe_div(counter_second, max(len(second_half), 1))
    feats["counter_play_improvement"] = (
        feats["counter_play_rate_second_half"] - feats["counter_play_rate_first_half"]
    )

    # ──────────────────────────────────────────────────────────────────────────
    # GROUP E — Risk / clutch behavior
    # ──────────────────────────────────────────────────────────────────────────
    heal_turns = [t for t in turns if t.get("action_chosen", "") == "Heal"]
    if heal_turns:
        feats["heal_avg_hp_pct_trigger"] = float(np.mean(
            [t.get("player_hp_before", 0) / max_hp for t in heal_turns]
        ))
    else:
        feats["heal_avg_hp_pct_trigger"] = 0.0

    clutch_turns = [t for t in turns if t.get("player_hp_before", 0) / max_hp < _CLUTCH_HP_PCT]
    if clutch_turns:
        clutch_counts: Dict[str, int] = {k: 0 for k in _ACTION_KEYS}
        for t in clutch_turns:
            key = _LABEL_TO_KEY.get(t.get("action_chosen", ""))
            if key:
                clutch_counts[key] += 1
        feats["clutch_action_entropy"] = _shannon_entropy(clutch_counts)
    else:
        feats["clutch_action_entropy"] = 0.0

    # fire_spell_usage_rate re-uses pct_fire_spell from Group A
    feats["fire_spell_usage_rate"] = feats["pct_fire_spell"]

    # comeback_flag — pass through from summary as integer 0/1
    feats["comeback_flag"] = 1 if summary.get("comeback_flag", False) else 0

    # ──────────────────────────────────────────────────────────────────────────
    # GROUP F — Decision timing
    # ──────────────────────────────────────────────────────────────────────────
    times = [t.get("time_taken_to_decide", 0) for t in turns]
    if times:
        mean_t = float(np.mean(times))
        feats["avg_reaction_time_ms"]    = mean_t
        feats["median_reaction_time_ms"] = float(np.median(times))
        feats["reaction_time_std"]       = float(np.std(times))
        feats["reaction_time_cv"]        = _safe_div(
            float(np.std(times)), max(mean_t, 1e-9)
        )
        feats["slow_decision_rate"] = _safe_div(
            sum(1 for ms in times if ms > _SLOW_DECISION_MS), len(times)
        )
    else:
        feats["avg_reaction_time_ms"]    = 0.0
        feats["median_reaction_time_ms"] = 0.0
        feats["reaction_time_std"]       = 0.0
        feats["reaction_time_cv"]        = 0.0
        feats["slow_decision_rate"]      = 0.0

    # ──────────────────────────────────────────────────────────────────────────
    # GROUP G — Status effect handling
    # ──────────────────────────────────────────────────────────────────────────
    status_uptime = sum(
        1 for t in turns if len(t.get("status_effects_active", [])) > 0
    )
    feats["status_effect_uptime_rate"] = _safe_div(status_uptime, n_turns)

    # turns_to_clear_weakened: average gap (in turns) between a "Weakened"
    # status appearing and it no longer appearing. 0 if never afflicted.
    weakened_gaps: List[int] = []
    in_weakened = False
    weakened_start = 0
    for t in turns:
        effects = t.get("status_effects_active", [])
        tn = t.get("turn_number", 0)
        has_weakened = "Weakened" in effects
        if has_weakened and not in_weakened:
            in_weakened = True
            weakened_start = tn
        elif not has_weakened and in_weakened:
            in_weakened = False
            gap = tn - weakened_start
            if gap > 0:
                weakened_gaps.append(gap)
    feats["turns_to_clear_weakened"] = float(np.mean(weakened_gaps)) if weakened_gaps else 0.0

    # ──────────────────────────────────────────────────────────────────────────
    # GROUP H — Sequence / transition patterns
    # NOTE: action_bigram_<a>_<b> columns are added separately via
    #       add_bigram_features() because they require a second pass across
    #       all matches to identify the dataset-wide top-5 bigrams.
    # ──────────────────────────────────────────────────────────────────────────

    # repeat_action_rate: fraction of turns where action == previous action
    action_seq = [t.get("action_chosen", "") for t in turns]
    repeat_count = sum(
        1 for i in range(1, len(action_seq))
        if action_seq[i] == action_seq[i - 1] and action_seq[i] != ""
    )
    feats["repeat_action_rate"] = _safe_div(repeat_count, max(len(action_seq) - 1, 1))

    # post_damage_defensive_rate: of turns immediately following a turn where
    # damage_taken > threshold, fraction where NEXT action was Rest or Heal
    _DEFENSIVE_ACTIONS = {"Rest & Recharge", "Heal"}
    post_damage_total = 0
    post_damage_defensive = 0
    for i in range(len(turns) - 1):
        if turns[i].get("damage_taken", 0) > _REACTIVE_DMG_THRESHOLD:
            post_damage_total += 1
            if turns[i + 1].get("action_chosen", "") in _DEFENSIVE_ACTIONS:
                post_damage_defensive += 1
    feats["post_damage_defensive_rate"] = _safe_div(post_damage_defensive, max(post_damage_total, 1))

    # ──────────────────────────────────────────────────────────────────────────
    # GROUP I — Outcome (label use only, EXCLUDED from model input)
    # ──────────────────────────────────────────────────────────────────────────
    feats["outcome_won"] = summary.get("outcome", "loss") == "win"

    return feats


# ─── Multi-match bigram second pass ──────────────────────────────────────────

def compute_top_bigrams(
    all_turns: List[List[Dict[str, Any]]],
    top_n: int = 5,
) -> List[str]:
    """
    Second-pass over all matches to identify the top-N most frequent
    action bigrams across the entire dataset.

    Returns list of bigram column names like 'action_bigram_quick_slash_fireball'.
    Call this AFTER loading all matches, then pass the result to add_bigram_features().
    """
    from collections import Counter

    bigram_counter: Counter = Counter()
    for turns in all_turns:
        seq = [_LABEL_TO_KEY.get(t.get("action_chosen", ""), "") for t in turns]
        for i in range(len(seq) - 1):
            if seq[i] and seq[i + 1]:
                bigram_counter[(seq[i], seq[i + 1])] += 1

    top = bigram_counter.most_common(top_n)
    return [f"action_bigram_{a}_{b}" for (a, b), _ in top]


def add_bigram_features(
    feature_dicts: List[Dict[str, Any]],
    all_turns: List[List[Dict[str, Any]]],
    top_bigram_cols: Optional[List[str]] = None,
    top_n: int = 5,
) -> List[str]:
    """
    Mutates each feature dict in-place by adding bigram frequency columns.

    Parameters
    ----------
    feature_dicts   : list of feature dicts, one per match
    all_turns       : list of turn lists, aligned with feature_dicts
    top_bigram_cols : pre-computed bigram column names (pass None to compute here)
    top_n           : number of top bigrams to track

    Returns
    -------
    List of bigram column names added (useful for downstream callers).
    """
    if top_bigram_cols is None:
        top_bigram_cols = compute_top_bigrams(all_turns, top_n=top_n)

    # Parse bigram column names back into (a, b) key tuples
    bigram_pairs: List[tuple] = []
    for col in top_bigram_cols:
        parts = col[len("action_bigram_"):]
        matched = False
        for ka in _ACTION_KEYS:
            if parts.startswith(ka + "_"):
                kb = parts[len(ka) + 1:]
                if kb in _ACTION_KEYS:
                    bigram_pairs.append((ka, kb))
                    matched = True
                    break
        if not matched:
            bigram_pairs.append(("", ""))  # sentinel for unrecognised cols

    for feat_dict, turns in zip(feature_dicts, all_turns):
        seq = [_LABEL_TO_KEY.get(t.get("action_chosen", ""), "") for t in turns]
        n_seq = max(len(seq) - 1, 1)
        local_counts: Dict[tuple, int] = {}
        for i in range(len(seq) - 1):
            if seq[i] and seq[i + 1]:
                key = (seq[i], seq[i + 1])
                local_counts[key] = local_counts.get(key, 0) + 1

        for col, pair in zip(top_bigram_cols, bigram_pairs):
            feat_dict[col] = _safe_div(local_counts.get(pair, 0), n_seq)

    return top_bigram_cols


# ─── Bulk loader ─────────────────────────────────────────────────────────────

def load_all_matches(logs_dir: str) -> List[Dict[str, Any]]:
    """
    Walk logs_dir recursively, load every match_*.json file,
    and return a list of raw match JSON dicts with a ``_source_file`` key added.
    """
    import os
    import json

    records = []
    for root, _dirs, files in os.walk(logs_dir):
        for fname in files:
            if fname.startswith("match_") and fname.endswith(".json"):
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data["_source_file"] = fpath
                    records.append(data)
                except Exception as e:
                    print(f"[extract_features] Warning: could not load {fpath}: {e}")
    return records


def build_feature_dataset(logs_dir: str, add_bigrams: bool = True):
    """
    End-to-end convenience: load all matches, extract features (including
    bigram second pass), and return a pandas DataFrame.

    The column ``outcome_won`` is included but should be excluded from model
    input features by callers. Metadata columns start with ``_``.
    """
    import pandas as pd

    raw_matches = load_all_matches(logs_dir)
    if not raw_matches:
        raise FileNotFoundError(f"No match JSON files found under: {logs_dir}")

    feature_dicts = [extract_match_features(m) for m in raw_matches]

    # Attach metadata (not model features)
    for fd, m in zip(feature_dicts, raw_matches):
        fd["_source_file"] = m.get("_source_file", "")
        fd["_player_id"]   = m.get("summary", {}).get("player_id", "")
        fd["_match_id"]    = m.get("summary", {}).get("match_id",  "")

    if add_bigrams:
        all_turns = [m.get("turns", []) for m in raw_matches]
        add_bigram_features(feature_dicts, all_turns)

    return pd.DataFrame(feature_dicts)


# ─── CLI smoke-test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os

    logs_dir = os.path.join(os.path.dirname(__file__), "logs")
    print(f"Loading matches from: {logs_dir}")
    df = build_feature_dataset(logs_dir)

    meta_cols  = [c for c in df.columns if c.startswith("_")]
    label_cols = ["outcome_won"]
    feat_cols  = [c for c in df.columns if c not in meta_cols and c not in label_cols]

    print(f"\n{'='*60}")
    print(f"Matches loaded  : {len(df)}")
    print(f"Feature columns : {len(feat_cols)}")
    print(f"{'='*60}")
    print("Feature names:")
    for fc in feat_cols:
        print(f"  {fc}")
