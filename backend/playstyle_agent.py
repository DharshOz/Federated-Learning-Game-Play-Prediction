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
GROQ_MODEL   = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

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

    @classmethod
    def _sanitize_result(cls, res: dict) -> dict:
        """Strip any mention of internal provider names like Groq/Grok from agent output."""
        if not isinstance(res, dict):
            return res
        import re
        pattern = re.compile(r'gro[qk](?:[\'-]agent)?', re.IGNORECASE)
        clean = {}
        for k, v in res.items():
            if isinstance(v, str):
                clean[k] = pattern.sub("AI Tactical Agent", v)
            elif isinstance(v, list):
                clean[k] = [
                    pattern.sub("AI Tactical Agent", item) if isinstance(item, str) else item
                    for item in v
                ]
            else:
                clean[k] = v
        return clean

    @classmethod
    def _tactical_heuristic_analysis(cls, match_data: dict, ml_prediction: dict = None) -> dict:
        summary = match_data.get("summary", match_data)
        turns = match_data.get("turns", [])

        # Derive label and confidence
        pred_label = (ml_prediction or {}).get("persona") or summary.get("persona_label")
        conf_pct = float((ml_prediction or {}).get("confidence_pct", 88.0))

        counter_rate = float(summary.get("counter_play_rate", 0.0)) * 100
        combos = int(summary.get("total_combos_triggered", 0))
        total_turns = int(summary.get("total_turns", len(turns) or 1))
        hero = summary.get("hero_class", "Hero")
        boss = summary.get("boss_variant", "Minotaur")
        outcome = summary.get("outcome", "match")

        reserves = summary.get("avg_resource_reserve", {})
        avg_p = float(reserves.get("avg_power", 50.0))
        avg_xp = float(reserves.get("avg_xp", 45.0))

        action_freq = summary.get("action_frequency_distribution", {})

        if not pred_label:
            if counter_rate >= 60.0 or action_freq.get("rest", 0) >= 0.25:
                pred_label = "Defensive"
            elif action_freq.get("fireball", 0) + action_freq.get("fire_spell", 0) >= 0.35:
                pred_label = "Aggressive"
            elif combos > 0 or counter_rate >= 40.0:
                pred_label = "Optimal"
            else:
                pred_label = "Random"

        conf_str = "High" if conf_pct >= 75.0 else "Medium"

        # Determine Counter-Play Grade
        if counter_rate >= 75.0:
            grade = "A"
            grade_desc = f"Grade A ({counter_rate:.1f}% counter rate) - exceptional reading of boss telegraphs."
        elif counter_rate >= 50.0:
            grade = "B"
            grade_desc = f"Grade B ({counter_rate:.1f}% counter rate) - consistent soft-counter mitigation against heavy strikes."
        elif counter_rate >= 30.0:
            grade = "C"
            grade_desc = f"Grade C ({counter_rate:.1f}% counter rate) - moderate response to telegraphed threat indicators."
        else:
            grade = "D"
            grade_desc = f"Grade D ({counter_rate:.1f}% counter rate) - prioritized offense over mitigating boss telegraphs."

        # Risk Profile
        if pred_label == "Aggressive":
            risk = "High Risk / Offensive Focus"
        elif pred_label == "Defensive":
            risk = "Cautious / Survival Focus"
        elif pred_label == "Optimal":
            risk = "Calculated Tactical Balance"
        else:
            risk = "Volatile / Unpredictable"

        # Resource Management
        if (avg_p + avg_xp) >= 80:
            res_mgmt = "Excellent (Sustained peak power for passive mitigation and damage scaling)"
        elif (avg_p + avg_xp) >= 50:
            res_mgmt = "Good (Balanced ability expenditure with steady recovery cycles)"
        else:
            res_mgmt = "Average (Low reserves during pivotal combat rounds)"

        # Combo Usage
        combo_note = f"Executed ({combos} combo sequence{'s' if combos > 1 else ''})" if combos > 0 else "Underutilized (Cross-turn action chaining was omitted)"

        # Reasoning Narrative
        if pred_label == "Optimal":
            reasoning = (
                f"Exhibited master-level tactical sequencing across {total_turns} turns against {boss}. "
                f"Balanced offensive spells with soft-counter mitigation ({counter_rate:.1f}% rate) and maintained disciplined resource reserves "
                f"(avg {avg_p:.0f} Power / {avg_xp:.0f} XP), capitalizing on optimal vulnerability windows."
            )
        elif pred_label == "Aggressive":
            reasoning = (
                f"Favored relentless offensive pressure throughout the {total_turns}-turn encounter with {boss}. "
                f"Prioritized direct damage spells over reactive shielding, trading damage directly and forcing aggressive tempo."
            )
        elif pred_label == "Defensive":
            reasoning = (
                f"Adopted a highly disciplined attrition strategy across {total_turns} turns against {boss}. "
                f"Actively mitigated incoming boss damage through Rest & Recharge and tactical counters ({counter_rate:.1f}% rate), prioritizing longevity."
            )
        else:
            reasoning = (
                f"Demonstrated an erratic action cadence across {total_turns} turns against {boss}. "
                f"Exhibited high action variance with unpredictable transitions between attacks and recovery."
            )

        # Strengths & Weaknesses
        strengths = []
        if counter_rate >= 50.0:
            strengths.append(f"Prompt soft-counter reactions against telegraphed boss attacks ({counter_rate:.1f}%)")
        else:
            strengths.append("High offensive throughput during active combat windows")
        if (avg_p + avg_xp) >= 60.0:
            strengths.append("Disciplined resource economy maintaining offensive & defensive thresholds")
        elif combos > 0:
            strengths.append(f"Successful cross-turn combo triggers ({combos} executed)")
        else:
            strengths.append("Aggressive engagement pacing keeping boss under continuous pressure")

        weaknesses = []
        if counter_rate < 50.0:
            weaknesses.append("Vulnerability to telegraphed heavy spells due to unmitigated strikes")
        if combos == 0:
            weaknesses.append("Missed high-value cross-turn synergy combos (e.g. Soaked Ignition)")
        if (avg_p + avg_xp) < 50.0:
            weaknesses.append("Resource reserve dips delayed access to heavy finishing spells")
        if not weaknesses:
            weaknesses.append("Occasional downtime while waiting for spell cooldown resets")

        # Actionable Coaching Tip
        if hero == "Fire Wizard" and action_freq.get("fire_spell", 0) > 0:
            coaching_tip = "Cast Rest & Recharge immediately before Fire Spell to trigger Channelled Inferno and waive all 20 HP recoil damage."
        elif combos == 0:
            coaching_tip = "Open with Water Arrow to weaken the boss, then cast Fireball next turn to trigger Soaked Ignition and double burn damage to 16 HP/turn."
        elif counter_rate < 50.0:
            coaching_tip = "Track boss telegraph indicators: Water Arrow mitigates incoming heavy strikes by 65%, while Rest raises a 60% Perfect Guard absorption shield."
        else:
            coaching_tip = "Maintain resource reserves above 50 Power to preserve the passive +20% outgoing damage bonus and +25% damage mitigation."

        agent_summary = f"Tactical assessment designates player as {pred_label} with {conf_str.lower()} consistency across {total_turns} rounds."

        return {
            "playstyle_label": pred_label,
            "playstyle_confidence": conf_str,
            "playstyle_reasoning": reasoning,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "missed_opportunities": ["Combo chains were omitted during early exchanges" if combos == 0 else "Minor delays during ability cooldowns"],
            "key_moment": f"Turn {max(1, total_turns // 2)}: Tactical engagement against {boss} deciding match trajectory.",
            "resource_management": res_mgmt,
            "counter_play_grade": grade,
            "counter_play_grade_desc": grade_desc,
            "risk_profile": risk,
            "combo_usage": combo_note,
            "coaching_tip": coaching_tip,
            "agent_summary": agent_summary,
            "_agent_engine": "Tactical Intelligence Agent"
        }

    def analyse(self, match_data: dict, ml_prediction: dict = None) -> dict:
        """
        Run agent analysis on a completed match.
        Returns structured insight dict with detailed tactical analysis and strategic reasoning.
        """
        api_key = self.current_api_key
        if api_key and not api_key.startswith("gsk_your_groq_api_key"):
            user_message = build_agent_context(match_data, ml_prediction)
            try:
                t0 = time.time()
                result = self._call_groq(user_message)
                elapsed = round(time.time() - t0, 2)
                result["_agent_latency_s"] = elapsed
                result["_agent_engine"] = "AI Tactical Agent"
                return self._sanitize_result(result)
            except Exception as e:
                print(f"[PlaystyleAgent] Remote Groq agent notice ({self.current_model}): {e}. Applying local tactical assessment engine.")
        else:
            print(f"[PlaystyleAgent] Setup notice: GROQ_API_KEY is not configured in .env. Please add your Groq API key (GROQ_API_KEY=gsk_...) to the root .env file to enable remote LLM strategic analysis with model '{self.current_model}'. Using embedded tactical analysis engine.")

        return self._tactical_heuristic_analysis(match_data, ml_prediction)


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
