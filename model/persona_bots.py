"""
persona_bots.py — Scripted Bot Personas for Arcane Clash Playstyle Classifier (Phase 1).

Runs 4 deterministic-strategy bots against the existing entity combat math (Entity.perform_attack,
Entity.apply_turn_effects, Entity.plan_next_attack) WITHOUT reimplementing combat math.
Each bot produces labeled match logs in the same JSON schema as real human logs.

Personas:
  - Aggressive : picks highest-expected-damage available action; heals only below 20% HP
  - Defensive  : always counters the telegraph if a counter exists; heals below 50% HP
  - Optimal    : counters telegraphs when beneficial AND manages resources before Fire Spell/Fireball
  - Random     : picks a uniformly random available (non-greyed-out) action each turn

Usage:
    python persona_bots.py           # runs all 4 personas, 100 matches each
    python persona_bots.py --dry-run # quick sanity check (5 matches per persona)
"""

import os
import sys
import json
import uuid
import random
import time
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

# Add project root and game directory to path so we can import entity and adaptive_weighting
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.abspath(os.path.join(_BASE_DIR, ".."))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)
sys.path.insert(0, os.path.join(_ROOT_DIR, "game"))

from entity import Entity
from adaptive_weighting import AdaptiveBossMemory

# ─── Reproducibility ─────────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)

# ─── Game constants (mirrors game.py) ────────────────────────────────────────
HERO_CONFIGS = [
    {"name": "Fire Wizard",       "hp": 120, "atk": 14},
    {"name": "Lightning Mage",    "hp": 100, "atk": 16},
    {"name": "Wanderer Magician", "hp": 110, "atk": 12},
]

VILLAIN_CONFIGS = [
    {"name": "Minotaur I",   "hp": 120, "atk": 12},
    {"name": "Minotaur II",  "hp": 150, "atk": 14},
    {"name": "Minotaur III", "hp": 180, "atk": 16},
]

# Player-usable actions only (no enrage — that's boss-only)
PLAYER_ACTIONS = ["quick_slash", "fireball", "water_arrow", "water_spell", "fire_spell", "heal", "rest"]

# Expected damage per action (base_dmg * hit_chance — used by Aggressive bot)
_EXPECTED_DAMAGE = {k: Entity.ATTACKS[k]["base_dmg"] * Entity.ATTACKS[k]["hit_chance"]
                    for k in PLAYER_ACTIONS}

# Logs directory
LOGS_DIR = os.path.join(_ROOT_DIR, "logs")

# Counter-play soft rules (mirrors game.py _evaluate_counter_play)
_HEAVY_ATTACKS = {"fireball", "fire_spell", "water_spell"}
_ALL_ATTACKS   = {"quick_slash", "fireball", "water_arrow", "water_spell", "fire_spell"}


# ─── Counter-play helper (mirrors game.py logic) ──────────────────────────────

def _evaluate_counter(hero_key: str, boss_telegraph_key: Optional[str], hero_hp: int, max_hp: int) -> bool:
    """Return True if hero_key is a meaningful counter to boss_telegraph_key."""
    if not boss_telegraph_key or boss_telegraph_key == "???":
        return False
    if boss_telegraph_key in _HEAVY_ATTACKS:
        if hero_key in ("rest", "water_arrow"):
            return True
    if boss_telegraph_key in _ALL_ATTACKS:
        if hero_key in ("water_arrow", "rest"):
            return True
    if boss_telegraph_key == "rest":
        if hero_key in _ALL_ATTACKS:
            return True
    if hero_hp < max_hp * 0.25 and hero_key in ("heal", "rest"):
        return True
    return False


# ─── Persona decision functions ───────────────────────────────────────────────

def _available_actions(hero: Entity) -> List[str]:
    """Return all player actions the hero can currently use."""
    return [k for k in PLAYER_ACTIONS if hero.can_use(k)]


def decide_aggressive(hero: Entity, boss_telegraph: Optional[str], last_action: Optional[str]) -> str:
    """
    Aggressive: always picks highest-expected-damage available action.
    Heals only below 20% HP.
    """
    available = _available_actions(hero)
    if not available:
        return "rest"

    # Heal threshold
    if hero.hp / hero.max_hp < 0.20 and "heal" in available:
        return "heal"

    # Pick highest expected damage (ignoring telegraphs)
    # Among equal-damage actions, prefer those off cooldown
    damage_actions = [a for a in available if a not in ("heal", "rest")]
    if not damage_actions:
        return "rest" if "rest" in available else available[0]

    best = max(damage_actions, key=lambda a: _EXPECTED_DAMAGE.get(a, 0))
    return best


def decide_defensive(hero: Entity, boss_telegraph: Optional[str], last_action: Optional[str]) -> str:
    """
    Defensive: always counters the telegraph when a counter exists.
    Falls back to Water Arrow for general utility; heals below 50% HP.
    """
    available = _available_actions(hero)
    if not available:
        return "rest"

    # Heal threshold — defensive bot is cautious
    if hero.hp / hero.max_hp < 0.50 and "heal" in available:
        return "heal"

    # Counter the telegraph
    if boss_telegraph and boss_telegraph != "???":
        for candidate in ("rest", "water_arrow"):
            if candidate in available and _evaluate_counter(candidate, boss_telegraph, hero.hp, hero.max_hp):
                return candidate

    # Fallback: Water Arrow (weakens enemy), then rest, then anything
    for fallback in ("water_arrow", "rest", "quick_slash"):
        if fallback in available:
            return fallback
    return available[0]


def decide_optimal(hero: Entity, boss_telegraph: Optional[str], last_action: Optional[str]) -> str:
    """
    Optimal: counters telegraphs when beneficial AND saves resources
    (XP > 80, Power > 50) before using Fire Spell / Fireball for max damage.
    """
    available = _available_actions(hero)
    if not available:
        return "rest"

    # Emergency heal
    if hero.hp / hero.max_hp < 0.30 and "heal" in available:
        return "heal"

    # Counter the telegraph first
    if boss_telegraph and boss_telegraph != "???":
        for candidate in ("rest", "water_arrow"):
            if candidate in available and _evaluate_counter(candidate, boss_telegraph, hero.hp, hero.max_hp):
                # But don't counter if we're ready to fire spell / fireball
                resource_ready = (hero.xp >= 80 and hero.power >= 50)
                big_spell_ready = any(s in available for s in ("fire_spell", "fireball"))
                if not (resource_ready and big_spell_ready):
                    return candidate

    # Use Fire Spell or Fireball if resources are charged
    if hero.xp >= 80 and hero.power >= 50:
        for big in ("fire_spell", "fireball"):
            if big in available:
                return big

    # Build resources with rest if low
    if hero.xp < 40 or hero.power < 30:
        if "rest" in available:
            return "rest"

    # Default to reliable mid-damage attack
    for mid in ("water_arrow", "water_spell", "quick_slash"):
        if mid in available:
            return mid

    return available[0]


def decide_random(hero: Entity, boss_telegraph: Optional[str], last_action: Optional[str]) -> str:
    """Random: picks a uniformly random available (non-greyed-out) action."""
    available = _available_actions(hero)
    if not available:
        return "rest"
    return random.choice(available)


PERSONA_DECIDERS = {
    "Aggressive": decide_aggressive,
    "Defensive":  decide_defensive,
    "Optimal":    decide_optimal,
    "Random":     decide_random,
}


# ─── Combat simulation engine ────────────────────────────────────────────────

def simulate_match(
    hero_cfg: Dict[str, Any],
    villain_cfg: Dict[str, Any],
    persona_name: str,
    decider,
    player_id: str,
    match_index: int,
    max_turns: int = 80,
) -> Dict[str, Any]:
    """
    Simulate a full match using the game's existing Entity combat math.
    Returns a match payload in the same JSON schema as real match logs.
    """
    # Initialise entities
    hero    = Entity(hero_cfg["name"],    hero_cfg["hp"],    hero_cfg["atk"],    entity_type="hero")
    villain = Entity(villain_cfg["name"], villain_cfg["hp"], villain_cfg["atk"], entity_type="villain")

    adaptive_memory = AdaptiveBossMemory()
    match_id = f"m_{uuid.uuid4().hex[:10]}"

    turns_log: List[Dict[str, Any]] = []
    boss_phase = 1
    phase2_boss_turns = 0
    player_action_history = []
    quick_slash_streak = 0
    lowest_player_hp = hero.hp
    successful_counters = 0
    total_telegraphed = 0

    # Pre-compute first boss telegraph
    telegraphed_key, actual_key, is_feint, weights_snap = villain.plan_next_attack(
        adaptive_memory=adaptive_memory
    )
    telegraphed_label = Entity.ATTACKS.get(telegraphed_key, {}).get("label", telegraphed_key)

    last_action: Optional[str] = None
    won = False
    final_player_hp = 0

    for turn_number in range(1, max_turns + 1):
        # ── Capture pre-action state BEFORE tick effects (mirrors real game logger) ──
        player_hp_before    = hero.hp
        player_xp_before    = hero.xp
        player_power_before = hero.power
        boss_hp_before      = villain.hp

        status_effects = []
        if hero.is_burning:    status_effects.append("Burning")
        if hero.is_exhausted:  status_effects.append("Exhausted")
        if hero.is_weakened:   status_effects.append("Weakened")
        if hero.is_defending or hero.is_counter_shielded:
            status_effects.append("Shielded")

        cooldowns_snap = dict(hero.cooldowns)

        # ── Apply hero turn effects (DoT, regen, cooldown tick) ───────────────
        hero.apply_turn_effects()
        if hero.state == "dead":
            break

        # ── Bot decision ───────────────────────────────────────────────────────
        action_key = decider(hero, telegraphed_key, last_action)
        adaptive_memory.record_player_action(action_key)

        # ── Counter evaluation (mirrors game.py _evaluate_counter_play) ───────
        is_counter = _evaluate_counter(action_key, telegraphed_key, hero.hp, hero.max_hp)
        if telegraphed_key and telegraphed_key != "???":
            total_telegraphed += 1
            if is_counter:
                successful_counters += 1

        # Apply soft counter effects
        if is_counter:
            tkey = telegraphed_key
            if tkey in _HEAVY_ATTACKS and action_key == "water_arrow":
                villain.is_counter_weakened = True
            elif tkey in _HEAVY_ATTACKS and action_key == "rest":
                hero.is_counter_shielded = True

        # ── Execute hero attack ────────────────────────────────────────────────
        # Detect combos (simplified — checks last action for main combos)
        combo_name = None
        last_hist = player_action_history[-1] if player_action_history else None
        if action_key == "fireball" and last_hist and last_hist.get("action") == "water_arrow" and last_hist.get("hit"):
            combo_name = "Soaked Ignition"
        elif action_key == "quick_slash" and quick_slash_streak >= 3:
            combo_name = "Flurry Finisher"
        elif action_key == "fire_spell" and last_hist and last_hist.get("action") == "rest":
            combo_name = "Channelled Inferno"

        result = hero.perform_attack(action_key, villain, combo=combo_name)
        hit_success  = result.get("hit", False)
        damage_dealt = result.get("dmg", 0)

        # Update quick slash streak
        if action_key == "quick_slash":
            quick_slash_streak = 0 if combo_name == "Flurry Finisher" else quick_slash_streak + 1
        else:
            quick_slash_streak = 0

        player_action_history.append({"action": action_key, "hit": hit_success, "turn": turn_number})
        last_action = action_key

        # Check boss phase transition from hero damage
        hp_ratio = villain.hp / villain.max_hp
        if hp_ratio <= 0.32 and boss_phase < 3:
            boss_phase = 3
            villain.boss_phase = 3
        elif hp_ratio <= 0.65 and boss_phase < 2:
            boss_phase = 2
            villain.boss_phase = 2

        player_hp_after_hero  = hero.hp
        player_xp_after_hero  = hero.xp
        player_power_after     = hero.power
        boss_hp_after_hero     = villain.hp

        if villain.state == "dead":
            # Log this turn and exit
            turns_log.append(_build_turn_entry(
                match_id, player_id, hero_cfg["name"], turn_number,
                Entity.ATTACKS[action_key]["label"],
                telegraphed_label, is_counter, combo_name, boss_phase,
                player_hp_before, player_hp_after_hero,
                boss_hp_before, boss_hp_after_hero,
                player_xp_before, player_xp_after_hero,
                player_power_before, player_power_after,
                hit_success, damage_dealt, 0, status_effects, cooldowns_snap,
                time_taken_ms=random.randint(500, 8000),
                boss_adaptive_weights=weights_snap,
            ))
            if player_hp_after_hero < lowest_player_hp:
                lowest_player_hp = player_hp_after_hero
            won = True
            final_player_hp = hero.hp
            break

        # ── Villain turn ───────────────────────────────────────────────────────
        villain.apply_turn_effects()
        if villain.state == "dead":
            turns_log.append(_build_turn_entry(
                match_id, player_id, hero_cfg["name"], turn_number,
                Entity.ATTACKS[action_key]["label"],
                telegraphed_label, is_counter, combo_name, boss_phase,
                player_hp_before, player_hp_after_hero,
                boss_hp_before, villain.hp,
                player_xp_before, player_xp_after_hero,
                player_power_before, player_power_after,
                hit_success, damage_dealt, 0, status_effects, cooldowns_snap,
                time_taken_ms=random.randint(500, 8000),
                boss_adaptive_weights=weights_snap,
            ))
            won = True
            final_player_hp = hero.hp
            break

        villain_result = villain.perform_attack(actual_key, hero)
        damage_taken   = villain_result.get("dmg", 0) if villain_result.get("hit") else 0

        player_hp_final = hero.hp
        if player_hp_final < lowest_player_hp:
            lowest_player_hp = player_hp_final

        # Log the full turn
        turns_log.append(_build_turn_entry(
            match_id, player_id, hero_cfg["name"], turn_number,
            Entity.ATTACKS[action_key]["label"],
            telegraphed_label, is_counter, combo_name, boss_phase,
            player_hp_before, player_hp_final,
            boss_hp_before, villain.hp,
            player_xp_before, player_xp_after_hero,
            player_power_before, player_power_after,
            hit_success, damage_dealt, damage_taken, status_effects, cooldowns_snap,
            time_taken_ms=random.randint(500, 8000),
            boss_adaptive_weights=weights_snap,
        ))

        if hero.state == "dead":
            won = False
            final_player_hp = 0
            break

        # Advance boss phase tracking
        if boss_phase == 2:
            phase2_boss_turns += 1

        # Plan next telegraph
        telegraphed_key, actual_key, is_feint, weights_snap = villain.plan_next_attack(
            adaptive_memory=adaptive_memory
        )
        if boss_phase == 2 and (phase2_boss_turns % 3 == 0):
            telegraphed_key = "???"
            telegraphed_label = "???"
        else:
            telegraphed_label = Entity.ATTACKS.get(telegraphed_key, {}).get("label", telegraphed_key)
    else:
        # Max turns reached — treat as loss
        won = False
        final_player_hp = hero.hp

    # ── Build match summary ────────────────────────────────────────────────────
    n_turns = len(turns_log)
    action_counts: Dict[str, int] = {}
    total_xp = total_power = 0
    for t in turns_log:
        act = t["action_chosen"]
        action_counts[act] = action_counts.get(act, 0) + 1
        total_xp    += t["player_xp_before"]
        total_power += t["player_power_before"]

    action_freq = {a: round(c / n_turns, 4) if n_turns > 0 else 0
                   for a, c in action_counts.items()}
    avg_xp    = round(total_xp    / n_turns, 2) if n_turns > 0 else 0
    avg_power = round(total_power / n_turns, 2) if n_turns > 0 else 0
    counter_rate = round(successful_counters / total_telegraphed, 4) if total_telegraphed > 0 else 0.0
    comeback_flag = won and (lowest_player_hp <= hero_cfg["hp"] * 0.25)

    summary = {
        "match_id":                     match_id,
        "player_id":                    player_id,
        "hero_class":                   hero_cfg["name"],
        "boss_variant":                 villain_cfg["name"],
        "outcome":                      "win" if won else "loss",
        "total_turns":                  n_turns,
        "action_frequency_distribution": action_freq,
        "avg_resource_reserve":         {"avg_xp": avg_xp, "avg_power": avg_power},
        "counter_play_rate":            counter_rate,
        "comeback_flag":                comeback_flag,
        "final_hp_remaining":           max(0, int(final_player_hp)) if won else 0,
        "timestamp":                    datetime.now().isoformat(),
        # Bot-specific metadata (not in original schema but useful for labelling)
        "persona_label":                persona_name,
    }

    return {"summary": summary, "turns": turns_log}


def _build_turn_entry(
    match_id, player_id, hero_class, turn_number, action_label, telegraphed_label,
    is_counter, combo_triggered, boss_phase,
    hp_before, hp_after, boss_hp_before, boss_hp_after,
    xp_before, xp_after, power_before, power_after,
    hit_success, damage_dealt, damage_taken,
    status_effects, cooldowns, time_taken_ms, boss_adaptive_weights,
) -> Dict[str, Any]:
    return {
        "match_id":                      match_id,
        "player_id":                     player_id,
        "hero_class":                    hero_class,
        "turn_number":                   turn_number,
        "action_chosen":                 action_label,
        "boss_telegraphed_action":       telegraphed_label or "None",
        "action_matched_counter":        bool(is_counter),
        "combo_triggered":               combo_triggered,           # optional field — present
        "boss_phase_at_decision":        int(boss_phase or 1),      # optional field — present
        "boss_adaptive_weights_snapshot": dict(boss_adaptive_weights or {}),  # optional
        "player_hp_before":              int(hp_before),
        "player_hp_after":               int(hp_after),
        "boss_hp_before":                int(boss_hp_before),
        "boss_hp_after":                 int(boss_hp_after),
        "player_xp_before":              int(xp_before),
        "player_xp_after":              int(xp_after),
        "player_power_before":           int(power_before),
        "player_power_after":            int(power_after),
        "hit_success":                   bool(hit_success),
        "damage_dealt":                  int(damage_dealt),
        "damage_taken":                  int(damage_taken),
        "status_effects_active":         list(status_effects),
        "cooldowns_active":              {k: int(v) for k, v in cooldowns.items()},
        "time_taken_to_decide":          int(time_taken_ms),
    }


# ─── Batch runner ─────────────────────────────────────────────────────────────

def run_persona_matches(
    persona_name: str,
    n_matches: int = 100,
    seed: int = SEED,
) -> List[str]:
    """
    Run `n_matches` simulations for the given persona and save logs.
    Returns list of saved file paths.
    """
    random.seed(seed + hash(persona_name) % 10000)
    decider = PERSONA_DECIDERS[persona_name]
    saved_paths = []

    for i in range(n_matches):
        hero_cfg    = random.choice(HERO_CONFIGS)
        villain_cfg = random.choice(VILLAIN_CONFIGS)
        player_id   = f"bot_{persona_name.lower()}_{i:04d}"

        payload = simulate_match(
            hero_cfg    = hero_cfg,
            villain_cfg = villain_cfg,
            persona_name = persona_name,
            decider      = decider,
            player_id    = player_id,
            match_index  = i,
        )

        # Save to logs/<player_id>/match_<match_id>.json
        player_dir = os.path.join(LOGS_DIR, player_id)
        os.makedirs(player_dir, exist_ok=True)
        match_id   = payload["summary"]["match_id"]
        fpath      = os.path.join(player_dir, f"match_{match_id}.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        saved_paths.append(fpath)

        if (i + 1) % 20 == 0 or i == n_matches - 1:
            wins = sum(1 for p in saved_paths[-20:] if True)  # count saved
            print(f"  [{persona_name}] {i+1}/{n_matches} matches simulated")

    return saved_paths


def run_all_personas(n_matches: int = 100) -> Dict[str, List[str]]:
    """Run all 4 personas and return a dict of persona → saved file paths."""
    results = {}
    for persona in PERSONA_DECIDERS:
        print(f"\n{'='*50}")
        print(f"Simulating {n_matches} matches for persona: {persona}")
        print(f"{'='*50}")
        paths = run_persona_matches(persona, n_matches=n_matches)
        wins  = 0
        for p in paths:
            try:
                with open(p) as f:
                    data = json.load(f)
                if data["summary"]["outcome"] == "win":
                    wins += 1
            except Exception:
                pass
        print(f"  Win rate: {wins}/{n_matches} ({100*wins//n_matches}%)")
        results[persona] = paths
    return results


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run persona bot simulations for Arcane Clash")
    parser.add_argument("--matches", type=int, default=100,
                        help="Number of matches per persona (default: 100)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Quick test: 5 matches per persona")
    args = parser.parse_args()

    n = 5 if args.dry_run else args.matches
    print(f"\nArcane Clash — Persona Bot Simulation")
    print(f"Matches per persona : {n}")
    print(f"Seed                : {SEED}")
    print(f"Logs directory      : {LOGS_DIR}\n")

    all_results = run_all_personas(n_matches=n)

    total = sum(len(v) for v in all_results.values())
    print(f"\n{'='*50}")
    print(f"Done. Total match logs written: {total}")
    for persona, paths in all_results.items():
        print(f"  {persona:12s}: {len(paths)} files")
    print(f"{'='*50}")
