"""
playstyle_agent.py — Groq LLM Agent for Deep Playstyle Analysis in Arcane Clash.

Analyses player match logs with full game context (attack mechanics, boss strategies,
resource economy, counter-play rules) and returns a rich structured insight report
beyond what the neural classifier can provide.

The agent is called after match completion, receives cleaned turn-level data,
and returns a JSON analysis stored alongside the ML prediction.
"""

import os
import sys
import json
import time

def get_project_root() -> str:
    cur = os.path.dirname(os.path.abspath(__file__))
    while cur and os.path.dirname(cur) != cur:
        if os.path.exists(os.path.join(cur, "Assets")) or os.path.exists(os.path.join(cur, ".env")):
            return cur
        cur = os.path.dirname(cur)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

_ROOT = get_project_root()
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_ROOT, ".env"))
except Exception:
    pass

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# ─── System Prompt (full game context) ───────────────────────────────────────

SYSTEM_PROMPT = """You are the Arcane Clash Battle Analyst, an expert AI embedded inside a turn-based wizard RPG.
Your job is to deeply analyse a player's match log and produce structured strategic insights.

GAME RULES AND MECHANICS

COMBAT STRUCTURE
- Turn-based: player acts first each round, then the boss acts.
- The boss TELEGRAPHS its intended move before the player picks an action.
  A savvy player can read the telegraph and choose a counter.
- Boss has 3 phases (HP thresholds). Phase 2 adds mystery telegraphs.
  Phase 3 the boss gains feints (40% chance to switch moves last second).

PLAYER RESOURCES
- HP (varies by hero: Fire Wizard=120, Lightning Mage=100, Wanderer=110)
- XP (0-100, passive +8/turn, spent on abilities)
- Power (0-100, passive +5/turn, spent on abilities, also affects defense and offense)
  Power above 40: each +10 gives 2% incoming damage reduction (cap 25%)
  Power above 50: each +10 gives 2% outgoing damage bonus (cap 20%)

HERO CLASSES
- Fire Wizard    (HP 120, ATK 14): High damage fire mastery, but exhausted after heavy spells.
- Lightning Mage (HP 100, ATK 16): Fastest attacks, highest accuracy, fragile.
- Wanderer       (HP 110, ATK 12): Balanced all-rounder, versatile and resilient.

PLAYER ATTACKS

quick_slash    | Dmg 12 | Hit 90% | XP 5  | Power 8  | No CD | Safe reliable filler. Spam builds Flurry Finisher combo.
fireball       | Dmg 28 | Hit 70% | XP 20 | Power 25 | CD 3  | Burns enemy 8 dmg per turn for 2 turns. EXHAUSTS self (next hit -25% accuracy).
water_arrow    | Dmg 18 | Hit 80% | XP 12 | Power 15 | No CD | Weakens enemy by 40% (65% as a counter vs telegraphed heavy). Excellent resource-value.
water_spell    | Dmg 22 | Hit 65% | XP 18 | Power 20 | No CD | Risky. On HIT heals +10 HP. High variance pick.
fire_spell     | Dmg 35 | Hit 55% | XP 30 | Power 35 | CD 3  | TRIPLE damage if XP>80 or Power>80. Costs 20 HP self-recoil (waived by Channelled Inferno combo).
heal           | Dmg 0  | Hit 100%| XP 10 | Power 0  | No CD | +25 HP, +15 Power. Always succeeds. Pure recovery.
rest           | Dmg 0  | Hit 100%| XP 0  | Power 0  | No CD | FREE. +20 XP +25 Power (diminishing). Raises shield that absorbs 35-60% of next hit.

COMBO CHAINS
- Soaked Ignition: Water Arrow HIT then Fireball = burn DoT DOUBLED to 16 per turn.
- Flurry Finisher: Quick Slash x3 streak then 4th Quick Slash = guaranteed hit plus 50% crit damage.
- Channelled Inferno: Rest then Fire Spell = Fire Spell 20 HP self-recoil is waived entirely.

BOSS MECHANICS
- Boss uses: quick_slash, fireball, water_arrow, water_spell, rest, enrage (Phase 2+)
- Boss rests to rebuild resources.
- Boss adapts to player patterns over time.

COUNTER-PLAY RULES (what counts as a good counter)
- Boss telegraphs heavy attack (fireball/fire_spell/water_spell) -> Player uses REST or WATER ARROW = good counter.
- Boss telegraphs any attack -> Player WATER ARROW or REST = counter.
- Boss telegraphs REST -> Player attacks = punish the opening.
- Player HP below 30% -> HEAL or REST = emergency defensive counter.

STRATEGIC ARCHETYPES
- Optimal: Saves XP+Power for Fire Spell triple-damage window. Counters telegraphs intelligently. Uses combos.
- Defensive: Frequent Rest/Heal. Counters boss heavily. Prioritises survival over damage.
- Aggressive: Spams high-dmg spells without waiting for resources. Ignores telegraphs. Takes big risks.
- Random: Erratic action selection with no discernible tactical pattern. High action entropy.

YOUR TASK
Analyse the match data and return ONLY valid JSON with no markdown fences or extra text.

Required JSON schema:
{
  "playstyle_label": "Aggressive or Defensive or Optimal or Random",
  "playstyle_confidence": "High or Medium or Low",
  "playstyle_reasoning": "2-3 sentences explaining why this label fits based on concrete turn evidence",
  "strengths": ["strength 1", "strength 2"],
  "weaknesses": ["weakness 1", "weakness 2"],
  "missed_opportunities": ["specific tactical opportunity the player missed based on turn data"],
  "key_moment": "Description of the single most defining moment in this match with turn number action and context",
  "resource_management": "Excellent or Good or Average or Poor with one sentence justification",
  "counter_play_grade": "A or B or C or D or F with one sentence justification",
  "risk_profile": "Reckless or Balanced or Cautious",
  "combo_usage": "None or Attempted or Executed with brief note on whether player used combo chains",
  "coaching_tip": "A single actionable coaching tip tailored to this player specific patterns",
  "agent_summary": "1-2 sentence punchy narrative summary of this player battle identity"
}

Be specific. Reference actual actions, turn numbers, HP values, and resource states from the data provided."""


# ─── Context builder: clean & compress turn data for LLM ─────────────────────

_TURN_KEEP_FIELDS = {
    "turn_number", "action_chosen", "boss_telegraphed_action",
    "action_matched_counter", "player_hp_before", "boss_hp_before",
    "player_xp_before", "player_power_before",
    "hit_success", "damage_dealt", "damage_taken",
    "player_hp_after", "boss_hp_after",
    "combo_triggered", "boss_phase_at_decision",
}

_SUMMARY_KEEP_FIELDS = {
    "hero_class", "boss_variant", "outcome", "total_turns",
    "action_frequency_distribution", "counter_play_rate",
    "total_combos_triggered", "max_boss_phase", "comeback_flag",
    "final_hp_remaining", "avg_resource_reserve",
}


def _clean_turn(t: dict) -> dict:
    """Strip heavy internal fields, keep only what the agent needs."""
    clean = {k: v for k, v in t.items() if k in _TURN_KEEP_FIELDS}
    if "action_matched_counter" in clean:
        clean["countered"] = "YES" if clean.pop("action_matched_counter") else "no"
    return clean


def _sample_turns(turns: list, max_turns: int = 20) -> list:
    """
    Sample a representative subset of turns:
    - Always include first 3 and last 3
    - Include turns where combos triggered or HP dropped below 35
    - Fill remainder evenly from the middle
    """
    if not turns:
        return []
    if len(turns) <= max_turns:
        return [_clean_turn(t) for t in turns]

    key_indices = set()
    for i in range(min(3, len(turns))):
        key_indices.add(i)
    for i in range(max(0, len(turns) - 3), len(turns)):
        key_indices.add(i)

    for i, t in enumerate(turns):
        if t.get("combo_triggered"):
            key_indices.add(i)
        if t.get("player_hp_before", 100) < 35:
            key_indices.add(i)
        if t.get("action_matched_counter"):
            key_indices.add(i)

    remaining = max_turns - len(key_indices)
    step = max(1, len(turns) // max(remaining, 1))
    for i in range(0, len(turns), step):
        if len(key_indices) >= max_turns:
            break
        key_indices.add(i)

    selected = sorted(key_indices)[:max_turns]
    return [_clean_turn(turns[i]) for i in selected]


def build_agent_context(match_data: dict, ml_prediction: dict = None) -> str:
    """Build a compact, informative string to feed the agent as user message."""
    summary_raw = match_data.get("summary", match_data)
    summary = {k: v for k, v in summary_raw.items() if k in _SUMMARY_KEEP_FIELDS}

    turns = match_data.get("turns", [])
    sampled = _sample_turns(turns, max_turns=20)

    context = {
        "match_summary": summary,
        "total_turns_in_log": len(turns),
        "sampled_turns": sampled,
    }

    if ml_prediction:
        context["ml_model_prediction"] = {
            "persona": ml_prediction.get("persona"),
            "confidence_pct": ml_prediction.get("confidence_pct"),
            "key_stats": ml_prediction.get("key_stats", {}),
        }

    return json.dumps(context, indent=2)


# ─── Agent ────────────────────────────────────────────────────────────────────

class PlaystyleAgent:
    """Groq-backed LLM agent that analyses Arcane Clash match logs."""

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or GROQ_API_KEY
        self.model   = model or GROQ_MODEL
        self._client = None

    @property
    def current_api_key(self) -> str:
        k = self.api_key or os.getenv("GROQ_API_KEY", "")
        if not k:
            try:
                from dotenv import load_dotenv
                load_dotenv(os.path.join(_ROOT, ".env"), override=True)
                k = os.getenv("GROQ_API_KEY", "")
            except Exception:
                pass
        return k

    @property
    def current_model(self) -> str:
        return os.getenv("GROQ_MODEL") or self.model or "openai/gpt-oss-120b"

    def _call_groq(self, user_message: str) -> dict:
        model = self.current_model
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.3,
            "max_tokens": 3000,
            "response_format": {"type": "json_object"},
        }
        # Attempt 1: Official Groq Python SDK if available
        try:
            import groq
            client = groq.Groq(api_key=self.current_api_key)
            resp = client.chat.completions.create(**payload)
            content = resp.choices[0].message.content.strip()
            return json.loads(content)
        except ImportError:
            pass
        except Exception as e:
            # If primary model fails on tokens or validation, re-raise to try REST or fallback
            raise e

        # Attempt 2: Direct REST call via requests / httpx
        import requests
        headers = {
            "Authorization": f"Bearer {self.current_api_key}",
            "Content-Type": "application/json"
        }
        res = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=40
        )
        if res.status_code != 200:
            raise RuntimeError(f"Groq API returned HTTP {res.status_code}: {res.text}")
        data = res.json()
        content = data["choices"][0]["message"]["content"].strip()
        return json.loads(content)

    def analyse(self, match_data: dict, ml_prediction: dict = None) -> dict:
        """
        Run agent analysis on a completed match.
        Returns structured insight dict, or error fallback dict.
        """
        api_key = self.current_api_key
        if not api_key:
            return self._unavailable_fallback("GROQ_API_KEY not set in .env", api_key_missing=True)

        user_message = build_agent_context(match_data, ml_prediction)

        try:
            t0 = time.time()
            result = self._call_groq(user_message)
            elapsed = round(time.time() - t0, 2)
            result["_agent_model"] = self.current_model
            result["_agent_latency_s"] = elapsed
            return result

        except json.JSONDecodeError as e:
            return self._unavailable_fallback(f"JSON parse error: {e}")
        except Exception as e:
            err_str = str(e)
            print(f"[PlaystyleAgent] Error: {err_str}")
            return self._unavailable_fallback(err_str)

    @classmethod
    def _unavailable_fallback(cls, reason: str, api_key_missing: bool = False) -> dict:
        tip = "Set GROQ_API_KEY in .env for deep AI coaching." if api_key_missing else "AI coaching currently calibrating. Check terminal for details."
        return {
            "playstyle_label": None,
            "playstyle_reasoning": "Agent analysis unavailable.",
            "coaching_tip": tip,
            "agent_summary": "Agent offline.",
            "_error": reason,
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_GLOBAL_AGENT = None

def get_playstyle_agent() -> PlaystyleAgent:
    global _GLOBAL_AGENT
    if _GLOBAL_AGENT is None:
        _GLOBAL_AGENT = PlaystyleAgent()
    return _GLOBAL_AGENT


def analyse_match(match_data: dict, ml_prediction: dict = None) -> dict:
    """Convenience function. Run agent analysis on a match dict."""
    return get_playstyle_agent().analyse(match_data, ml_prediction)
