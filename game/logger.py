"""
logger.py — Playstyle Data Logging Layer for Arcane Clash.

Captures per-turn decisions and per-match summaries for ML/analytics pipelines.
Decoupled from core combat logic and stores data locally in /logs/{player_id}/
and synchronizes asynchronously with the backend server.
"""

import os
import sys
import json
import uuid
import time
from datetime import datetime

ENABLE_LOGGING = True

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

LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")

_ACTIVE_PLAYER_ID = None

def get_active_player_id() -> str:
    """Retrieve the currently authenticated player ID or fallback to saved session."""
    global _ACTIVE_PLAYER_ID
    if _ACTIVE_PLAYER_ID:
        return _ACTIVE_PLAYER_ID
    
    session_file = os.path.join(PROJECT_ROOT, ".user_session.json")
    if os.path.exists(session_file):
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                uname = data.get("username")
                if uname:
                    _ACTIVE_PLAYER_ID = uname
                    return uname
        except Exception:
            pass

    _ACTIVE_PLAYER_ID = get_or_create_player_id()
    return _ACTIVE_PLAYER_ID

def set_active_player_id(player_id: str):
    """Set the global player identity across logging and telemetry."""
    global _ACTIVE_PLAYER_ID
    _ACTIVE_PLAYER_ID = player_id
    try:
        with open(os.path.join(PROJECT_ROOT, ".player_id"), "w", encoding="utf-8") as f:
            f.write(player_id)
    except Exception:
        pass

def get_or_create_player_id():
    """Retrieve or generate a persistent local player/client ID."""
    id_file = os.path.join(PROJECT_ROOT, ".player_id")
    try:
        if os.path.exists(id_file):
            with open(id_file, "r", encoding="utf-8") as f:
                pid = f.read().strip()
                if pid:
                    return pid
        new_id = f"player_{uuid.uuid4().hex[:8]}"
        with open(id_file, "w", encoding="utf-8") as f:
            f.write(new_id)
        return new_id
    except Exception:
        return "player_local"

class BattleLogger:
    """Observes and logs match sessions and turn decisions."""

    def __init__(self, player_id: str = None):
        self.enabled = ENABLE_LOGGING
        self.player_id = player_id or get_active_player_id()
        self.match_id = None
        self.hero_class = None
        self.boss_variant = None
        self.max_player_hp = 100
        self.lowest_player_hp = 100
        self.current_turn = 0
        self.turn_start_timestamp = None
        self.pending_turn_data = None
        self.turns = []
        self.total_telegraphed_threats = 0
        self.successful_counters = 0
        self.last_prediction = None
        self.last_agent_analysis = None

    def set_player(self, player_id: str):
        """Update player identity for session logging."""
        self.player_id = player_id
        set_active_player_id(player_id)

    def start_match(self, hero_class, boss_variant, max_player_hp=100):
        """Initialize a new battle logging session."""
        if not self.enabled:
            return
        self.player_id = get_active_player_id()
        self.last_prediction = None
        self.match_id = f"m_{uuid.uuid4().hex[:10]}"
        self.hero_class = hero_class
        self.boss_variant = boss_variant
        try:
            from backend.client_sync import get_client_sync
            get_client_sync().start_heartbeat_loop(self.player_id, hero_class)
        except Exception:
            pass
        self.max_player_hp = max_player_hp
        self.lowest_player_hp = max_player_hp
        self.current_turn = 0
        self.turn_start_timestamp = time.time()
        self.pending_turn_data = None
        self.turns = []
        self.total_telegraphed_threats = 0
        self.successful_counters = 0

    def mark_turn_start(self):
        """Record the timestamp when the player's turn begins."""
        self.turn_start_timestamp = time.time()

    def log_player_action(
        self,
        turn_number,
        action_chosen,
        boss_telegraphed_action,
        action_matched_counter,
        player_hp_before,
        boss_hp_before,
        player_xp_before,
        player_power_before,
        status_effects_active,
        cooldowns_active,
        hit_success,
        damage_dealt,
        player_hp_after,
        boss_hp_after,
        player_xp_after,
        player_power_after,
        time_taken_ms=None,
        combo_triggered=None,
        combo_chain_length_at_decision=0,
        boss_phase_at_decision=1,
        phase_transition_occurred=False,
        boss_adaptive_weights_snapshot=None,
    ):
        """Buffer player's turn action and state."""
        if not self.enabled or not self.match_id:
            return

        self.current_turn = turn_number
        if time_taken_ms is None:
            time_taken_ms = (
                int((time.time() - self.turn_start_timestamp) * 1000)
                if self.turn_start_timestamp
                else 0
            )

        if boss_telegraphed_action and boss_telegraphed_action not in ("None", "???"):
            self.total_telegraphed_threats += 1
            if action_matched_counter:
                self.successful_counters += 1

        if isinstance(status_effects_active, dict):
            status_effects_dict = dict(status_effects_active)
        elif isinstance(status_effects_active, (list, tuple, set)):
            status_effects_dict = {str(eff): True for eff in status_effects_active}
        else:
            status_effects_dict = {}

        if isinstance(cooldowns_active, dict):
            cooldowns_dict = dict(cooldowns_active)
        elif isinstance(cooldowns_active, (list, tuple, set)):
            cooldowns_dict = {str(cd): 1 for cd in cooldowns_active}
        else:
            cooldowns_dict = {}

        self.pending_turn_data = {
            "turn_number": turn_number,
            "action_chosen": action_chosen,
            "boss_telegraphed_action": boss_telegraphed_action,
            "action_matched_counter": bool(action_matched_counter),
            "time_taken_to_decide_ms": time_taken_ms,
            "player_hp_before": int(player_hp_before),
            "boss_hp_before": int(boss_hp_before),
            "player_xp_before": int(player_xp_before),
            "player_power_before": int(player_power_before),
            "player_status_effects": status_effects_dict,
            "cooldowns_active": cooldowns_dict,
            "hit_success": bool(hit_success),
            "damage_dealt": int(damage_dealt),
            "boss_action_chosen": None,
            "damage_taken": 0,
            "player_hp_after": int(player_hp_after),
            "boss_hp_after": int(boss_hp_after),
            "player_xp_after": int(player_xp_after),
            "player_power_after": int(player_power_after),
            "combo_triggered": combo_triggered,
            "combo_chain_length": combo_chain_length_at_decision,
            "boss_phase_at_decision": boss_phase_at_decision,
            "phase_transition_occurred": phase_transition_occurred,
            "boss_adaptive_weights_snapshot": boss_adaptive_weights_snapshot or {},
        }

    def log_boss_response(self, boss_action_chosen, damage_taken_by_player, player_hp_final):
        """Append enemy counter-action and commit full turn entry."""
        if not self.enabled or not self.pending_turn_data:
            return

        self.pending_turn_data["boss_action_chosen"] = boss_action_chosen
        self.pending_turn_data["damage_taken"] = int(damage_taken_by_player)
        self.pending_turn_data["player_hp_after"] = int(player_hp_final)
        if player_hp_final < self.lowest_player_hp:
            self.lowest_player_hp = player_hp_final

        self.turns.append(self.pending_turn_data)
        self.pending_turn_data = None

    def log_boss_turn_resolution(self, damage_taken_by_player, player_hp_final, boss_action_chosen=None):
        """Record boss resolution for the round (alias for log_boss_response)."""
        return self.log_boss_response(boss_action_chosen, damage_taken_by_player, player_hp_final)

    def end_match(self, won, final_player_hp):
        """Compute match summary, run AI prediction, and save local/remote logs."""
        if not self.enabled or not self.match_id:
            return

        if self.pending_turn_data:
            self.turns.append(self.pending_turn_data)
            self.pending_turn_data = None

        total_turns = len(self.turns)
        action_counts = {}
        total_xp_reserve = 0
        total_power_reserve = 0

        for t in self.turns:
            act = t.get("action_chosen", "Unknown")
            action_counts[act] = action_counts.get(act, 0) + 1
            total_xp_reserve += t.get("player_xp_before", 0)
            total_power_reserve += t.get("player_power_before", 0)

        action_freq = {
            act: round((count / total_turns), 4) if total_turns > 0 else 0
            for act, count in action_counts.items()
        }

        avg_xp = round(total_xp_reserve / total_turns, 2) if total_turns > 0 else 0
        avg_power = round(total_power_reserve / total_turns, 2) if total_turns > 0 else 0

        counter_rate = (
            round(self.successful_counters / self.total_telegraphed_threats, 4)
            if self.total_telegraphed_threats > 0
            else 0.0
        )

        comeback_flag = (
            won and (self.lowest_player_hp <= (self.max_player_hp * 0.25))
        )

        total_combos = sum(1 for t in self.turns if t.get("combo_triggered"))
        max_boss_phase = max((t.get("boss_phase_at_decision", 1) for t in self.turns), default=1)

        summary = {
            "match_id": self.match_id,
            "player_id": self.player_id,
            "hero_class": self.hero_class,
            "boss_variant": self.boss_variant,
            "outcome": "win" if won else "loss",
            "total_turns": total_turns,
            "action_frequency_distribution": action_freq,
            "avg_resource_reserve": {
                "avg_xp": avg_xp,
                "avg_power": avg_power,
            },
            "counter_play_rate": counter_rate,
            "total_combos_triggered": total_combos,
            "max_boss_phase": max_boss_phase,
            "comeback_flag": comeback_flag,
            "final_hp_remaining": max(0, int(final_player_hp if won else 0)),
            "timestamp": datetime.now().isoformat(),
        }

        match_payload = {
            "summary": summary,
            "turns": self.turns,
        }

        # ── Infer Player Attacking Playstyle Immediately After Match End ──
        try:
            from model.predictor import predict_match
            self.last_prediction = predict_match(match_payload)
            summary["prediction"] = self.last_prediction
        except Exception as e:
            print(f"[BattleLogger] Prediction error: {e}")
            self.last_prediction = None

        # ── Run Strategic AI Agent Analysis (synchronous baseline + async LLM enhancement) ───
        try:
            from backend.playstyle_agent import analyse_match
            self.last_agent_analysis = analyse_match(match_payload, self.last_prediction)
            match_payload["agent_analysis"] = self.last_agent_analysis
            summary["agent_analysis"] = self.last_agent_analysis
        except Exception as e:
            print(f"[BattleLogger] Agent analysis init notice: {e}")
            self.last_agent_analysis = None

        def _run_agent():
            try:
                from backend.playstyle_agent import analyse_match
                agent_result = analyse_match(match_payload, self.last_prediction)
                self.last_agent_analysis = agent_result
                match_payload["agent_analysis"] = agent_result
                summary["agent_analysis"] = agent_result
                # Re-save to disk with agent data included
                self._save_to_disk(match_payload)
                print(f"[BattleLogger] Strategic Agent analysis updated: {agent_result.get('playstyle_label','?')} ({agent_result.get('playstyle_confidence','?')})")
            except Exception as e:
                print(f"[BattleLogger] Strategic Agent update note: {e}")

        import threading
        t = threading.Thread(target=_run_agent, daemon=True, name="AgentAnalysisThread")
        t.start()

        self._save_to_disk(match_payload)

        # ── Asynchronously Dispatch to Universal Backend ────────────────
        try:
            from backend.client_sync import get_client_sync
            get_client_sync().send_match_payload(match_payload, self.last_prediction)
        except Exception:
            pass

        return self.last_prediction

    def _save_to_disk(self, payload):
        """Save the match data to the local client directory."""
        try:
            player_dir = os.path.join(LOGS_DIR, self.player_id)
            os.makedirs(player_dir, exist_ok=True)
            file_path = os.path.join(player_dir, f"match_{self.match_id}.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            print(f"[BattleLogger] Warning: failed to save match log: {e}")
