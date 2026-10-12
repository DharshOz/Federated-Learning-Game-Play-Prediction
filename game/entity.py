import random


class Entity:
    """Represents a game entity (hero or villain) with RPG stat bars."""

    def __init__(self, name, max_hp, atk, entity_type="hero"):
        self.name = name
        self.max_hp = max_hp
        self.hp = max_hp
        self.atk = atk
        self.entity_type = entity_type   # "hero" or "villain"
        self.state = "alive"             # alive | dead

        # Resource bars (0-100)
        self.xp        = 50
        self.max_xp    = 100
        self.power     = 70
        self.max_power = 100
        self.life      = max_hp              # mirrors hp for display

        # Status effects
        self.is_exhausted  = False       # -25% accuracy next turn
        self.is_burning    = False       # lose HP at turn start
        self.is_weakened   = False       # -40% outgoing damage
        self.is_defending  = False       # +35% incoming damage reduction (from Rest)
        self.is_counter_weakened = False # -65% outgoing damage on next hit (enhanced counter weaken)
        self.is_counter_shielded = False # +60% incoming damage reduction (enhanced counter shield)
        self.burn_damage   = 0
        self.status_timer  = 0
        self.cooldowns     = {}          # attack_key -> turns remaining
        self.boss_phase    = 1           # 1, 2, or 3 for boss phase shifts

        # Rested consecutive turns (diminishing returns on Rest)
        self._rest_count   = 0

    @property
    def status_effects(self):
        eff = {}
        if getattr(self, "is_burning", False):
            eff["burn"] = getattr(self, "status_timer", 1) or 1
        if getattr(self, "is_exhausted", False):
            eff["exhaust"] = 1
        if getattr(self, "is_weakened", False) or getattr(self, "is_counter_weakened", False):
            eff["weakened"] = 1
        if getattr(self, "is_defending", False) or getattr(self, "is_counter_shielded", False):
            eff["shield"] = 1
        return eff

    # ── POWER mechanics ──────────────────────────────────────────────────────
    # Power now has THREE live uses:
    #  1. Spending currency  – heavy attacks cost Power
    #  2. Passive defense    – each 10 pts above 40 = 2% dmg reduction (up to 25%)
    #  3. Offensive bonus    – each 10 pts above 50 = 2% dmg bonus   (up to 20%)

    def power_defense_mult(self):
        """Incoming damage multiplier from Power (lower = better defence)."""
        if self.power <= 40:
            return 1.0
        reduction = min(0.25, (self.power - 40) / 10 * 0.02)
        return 1.0 - reduction

    def power_offense_mult(self):
        """Outgoing damage multiplier from Power (higher = more damage)."""
        if self.power <= 50:
            return 1.0
        bonus = min(0.20, (self.power - 50) / 10 * 0.02)
        return 1.0 + bonus

    # ── Attack definitions ───────────────────────────────────────────────────

    ATTACKS = {
        "quick_slash": {
            "label": "Quick Slash",
            "base_dmg": 12,
            "hit_chance": 0.90,
            "xp_cost": 5,
            "power_cost": 8,
            "cooldown": 0,
            "desc": "Fast strike. High accuracy, low damage.",
            "effect": None,
            "icon": "fire_arrow",
        },
        "fireball": {
            "label": "Fireball",
            "base_dmg": 28,
            "hit_chance": 0.70,
            "xp_cost": 20,
            "power_cost": 25,
            "cooldown": 3,
            "desc": "Big fire damage. Burns enemy 2 turns. You get exhausted.",
            "effect": "burn_enemy",
            "side_effect": "exhaust_self",
            "icon": "fire_ball",
        },
        "water_arrow": {
            "label": "Water Arrow",
            "base_dmg": 18,
            "hit_chance": 0.80,
            "xp_cost": 12,
            "power_cost": 15,
            "cooldown": 0,
            "desc": "Piercing shot. Weakens enemy attack by 40% (65% vs telegraphed strikes).",
            "effect": "weaken_enemy",
            "icon": "water_arrow",
        },
        "water_spell": {
            "label": "Water Spell",
            "base_dmg": 22,
            "hit_chance": 0.65,
            "xp_cost": 18,
            "power_cost": 20,
            "cooldown": 0,
            "desc": "Risky heavy spell. On hit: heals you +10 HP.",
            "effect": "heal_self",
            "icon": "water_spell",
        },
        "fire_spell": {
            "label": "Fire Spell",
            "base_dmg": 35,
            "hit_chance": 0.55,
            "xp_cost": 30,
            "power_cost": 35,
            "cooldown": 3,
            "desc": "Devastating blast. Triple dmg if XP>80. Costs 20 HP.",
            "effect": "power_surge",
            "side_effect": "cost_hp_self",
            "icon": "fire_spell",
        },
        "heal": {
            "label": "Heal",
            "base_dmg": 0,
            "hit_chance": 1.0,
            "xp_cost": 10,
            "power_cost": 0,
            "cooldown": 0,
            "desc": "Recover 25 HP and +15 Power. Always works.",
            "effect": "heal_self_major",
            "icon": None,
        },
        "rest": {
            "label": "Rest & Recharge",
            "base_dmg": 0,
            "hit_chance": 1.0,
            "xp_cost": 0,
            "power_cost": 0,
            "cooldown": 0,
            "desc": "Skip attack. Gain +20 XP, +25 Power. Raise shield (absorbs 35%-60% dmg).",
            "effect": "rest_and_recharge",
            "icon": None,
        },
        "enrage": {
            "label": "Enrage",
            "base_dmg": 26,
            "hit_chance": 0.85,
            "xp_cost": 15,
            "power_cost": 20,
            "cooldown": 0,
            "desc": "Ferocious enraged slam. High damage.",
            "effect": None,
            "icon": "fire_ball",
        },
    }

    # Enemy attack pool (rest included so AI can also build power, enrage unlocked in Phase 2)
    ENEMY_ATTACKS = ["quick_slash", "fireball", "water_arrow", "water_spell", "rest", "enrage"]

    # ── can_use ───────────────────────────────────────────────────────────────

    def can_use(self, attack_key):
        """Return True if entity can afford this attack and it's off cooldown."""
        if self.cooldowns.get(attack_key, 0) > 0:
            return False
        if attack_key == "rest":
            return True          # rest is always free
        a = self.ATTACKS[attack_key]
        return self.xp >= a["xp_cost"] and self.power >= a["power_cost"]

    # ── perform_attack ────────────────────────────────────────────────────────

    def perform_attack(self, attack_key, target, combo=None):
        """
        Execute an attack / action.
        Supports combos:
          - "Soaked Ignition": doubles Fireball burn DoT to 16/turn
          - "Flurry Finisher": guaranteed hit and +50% crit damage
          - "Channelled Inferno": waives Fire Spell 20 HP recoil
        Returns: dict { hit, dmg, effect_msg, attack_key }
        """
        a = self.ATTACKS[attack_key]
        result = {"hit": False, "dmg": 0, "effect_msg": "", "attack_key": attack_key}

        # ── Rest (special: no target, no miss, instant return) ──────────────
        if a["effect"] == "rest_and_recharge":
            gain_xp    = max(5, 20 - self._rest_count * 5)   # diminishing returns
            gain_power = max(5, 25 - self._rest_count * 5)
            self.xp    = min(100, self.xp + gain_xp)
            self.power = min(100, self.power + gain_power)
            self.is_defending = True
            self._rest_count += 1
            shield_note = "  Shield UP!"
            result["effect_msg"] = f"+{gain_xp} XP  +{gain_power} Power{shield_note}"
            result["hit"]  = True
            result["dmg"]  = 0
            self.check_state()
            return result

        # Reset rest streak when actually attacking
        self._rest_count = 0

        # ── Deduct resource costs & apply cooldown ───────────────────────────
        self.xp    = max(0, self.xp    - a["xp_cost"])
        self.power = max(0, self.power - a["power_cost"])
        cd = a.get("cooldown", 0)
        if cd > 0:
            self.cooldowns[attack_key] = cd

        # ── Accuracy check ───────────────────────────────────────────────────
        hit_mod = 0.75 if self.is_exhausted else 1.0
        # Flurry Finisher combo guarantees a hit
        is_guaranteed_hit = (combo == "Flurry Finisher")
        if not is_guaranteed_hit and random.random() > a["hit_chance"] * hit_mod:
            result["effect_msg"] = "MISSED!"
            self.is_exhausted = False
            return result

        # ── Base damage with Power-offense bonus ─────────────────────────────
        dmg = a["base_dmg"]
        if combo == "Flurry Finisher":
            dmg = int(dmg * 1.5)  # +50% guaranteed crit damage
        if self.is_counter_weakened:
            dmg = int(dmg * 0.35)  # Enhanced counter weaken: 65% outgoing reduction
            self.is_counter_weakened = False
        elif self.is_weakened:
            dmg = int(dmg * 0.60)
        dmg = int(dmg * self.power_offense_mult())

        # Phase 3 Boss Desperation: 15% damage reduction on all villain attacks
        if self.entity_type == "villain" and getattr(self, "boss_phase", 1) == 3:
            dmg = max(1, int(dmg * 0.85))

        # ── Special effects ──────────────────────────────────────────────────
        effect = a.get("effect")
        side   = a.get("side_effect")

        if effect == "burn_enemy":
            target.is_burning  = True
            target.burn_damage = 16 if combo == "Soaked Ignition" else 8
            target.status_timer = 2
            if combo == "Soaked Ignition":
                result["effect_msg"] = "SOAKED IGNITION! 2x Burn Damage (16/turn)!"
            else:
                result["effect_msg"] = "Enemy is BURNING!"
        elif effect == "weaken_enemy":
            target.is_weakened  = True
            result["effect_msg"] = "Enemy is WEAKENED!"
        elif effect == "heal_self":
            self.hp   = min(self.max_hp, self.hp + 10)
            self.life = self.hp
            result["effect_msg"] = "+10 HP restored!"
        elif effect == "heal_self_major":
            self.hp    = min(self.max_hp, self.hp + 25)
            self.power = min(100, self.power + 15)
            self.life  = self.hp
            result["effect_msg"] = "+25 HP  +15 Power!"
            result["dmg"]  = 0
            result["hit"]  = True
            self.check_state()
            return result
        elif effect == "power_surge":
            if self.xp + a["xp_cost"] >= 80 or self.power + a["power_cost"] >= 80:
                dmg = dmg * 3
                result["effect_msg"] = "POWER SURGE! Triple damage!"

        # ── Side effects on self ─────────────────────────────────────────────
        if side == "exhaust_self":
            self.is_exhausted = True
        elif side == "cost_hp_self":
            if combo == "Channelled Inferno":
                # Combo waives the 20 HP self-recoil
                combo_note = "  (Channelled Inferno: 20 HP recoil waived!)"
                result["effect_msg"] = (result["effect_msg"] + combo_note) if result["effect_msg"] else "Recoil waived!"
            else:
                self.hp   = max(1, self.hp - 20)
                self.life = self.hp
                if result["effect_msg"]:
                    result["effect_msg"] += "  (lost 20 HP!)"
                else:
                    result["effect_msg"] = "You lost 20 HP!"

        # ── Apply damage with target defense ────────────────────────────────
        defense_mult = target.power_defense_mult()   # passive Power defense
        if target.is_counter_shielded:
            defense_mult *= 0.40                     # Perfect Guard counter: 60% reduction
            target.is_counter_shielded = False
            target.is_defending = False
        elif target.is_defending:
            defense_mult *= 0.65                     # Standard Rest shield: 35% reduction
            target.is_defending = False

        dmg = max(1, int(dmg * defense_mult))

        target.hp   = max(0, target.hp - dmg)
        target.life = target.hp
        result["hit"] = True
        result["dmg"] = dmg
        self.is_exhausted = False

        if combo == "Flurry Finisher":
            if result["effect_msg"]:
                result["effect_msg"] += " [FLURRY CRIT!]"
            else:
                result["effect_msg"] = "FLURRY CRIT (+50% Dmg)!"

        target.check_state()
        self.check_state()
        return result

    # ── Turn effects (DoT, passive regen, cooldowns) ─────────────────────────

    def tick_cooldowns(self):
        """Reduce remaining ability cooldown turns by 1."""
        for k in list(self.cooldowns.keys()):
            if self.cooldowns[k] > 0:
                self.cooldowns[k] -= 1
                if self.cooldowns[k] <= 0:
                    del self.cooldowns[k]

    def apply_turn_effects(self):
        """Called at the start of this entity's turn."""
        self.tick_cooldowns()
        msgs = []
        if self.is_burning and self.status_timer > 0:
            self.hp   = max(0, self.hp - self.burn_damage)
            self.life = self.hp
            msgs.append(f"Burn: -{self.burn_damage} HP!")
            self.status_timer -= 1
            if self.status_timer == 0:
                self.is_burning = False
                msgs.append("Burn faded.")

        # Passive XP/Power regen per turn
        self.xp    = min(100, self.xp    + 8)
        self.power = min(100, self.power + 5)
        self.check_state()
        return msgs

    # ── Enemy AI & Telegraphing ──────────────────────────────────────────────

    def plan_next_attack(self, feint_chance=None, adaptive_memory=None):
        """
        Boss intent planning: choose intended move for telegraphing with feint chance and adaptive memory.
        Returns: (telegraphed_key, actual_key, is_feint, weights_snapshot)
        """
        if feint_chance is None:
            # Phase 3 increases feint rate from 20% to 40%
            feint_chance = 0.40 if self.boss_phase == 3 else 0.20

        intended, weights_snapshot = self.choose_enemy_attack(adaptive_memory=adaptive_memory)
        usable = [k for k in self.ENEMY_ATTACKS if self.can_use(k) and (k != "enrage" or self.boss_phase >= 2)]
        if not usable:
            usable = ["quick_slash"]

        alternatives = [k for k in usable if k != intended]
        is_feint = False
        actual = intended
        telegraphed = intended

        if alternatives and random.random() < feint_chance:
            is_feint = True
            telegraphed = intended
            actual = random.choice(alternatives)

        return telegraphed, actual, is_feint, weights_snapshot

    def choose_enemy_attack(self, adaptive_memory=None):
        """Smart AI: evaluate situation and pick best action using adaptive memory weighting if available."""
        usable = [k for k in self.ENEMY_ATTACKS if self.can_use(k) and (k != "enrage" or self.boss_phase >= 2)]
        if not usable:
            usable = ["quick_slash"]

        # Critical low HP → heal or rest
        if self.hp < 30:
            if self.can_use("heal"):
                return "heal", {"heal": 1.0}
            if self.power < 40 and "rest" in usable:
                return "rest", {"rest": 1.0}

        # Both resources high → unleash powerful attack (including enrage if in phase 2+)
        if self.xp >= 80 and self.power >= 70:
            choices = [k for k in ["enrage", "fire_spell", "fireball", "water_spell"] if k in usable]
            if choices:
                act = random.choice(choices)
                return act, {act: 1.0}

        # Power low → rest to recharge and gain shield
        if self.power < 20 and "rest" in usable:
            return "rest", {"rest": 1.0}

        # Adaptive memory weighting (in-match local heuristic)
        if adaptive_memory:
            return adaptive_memory.compute_action_weights(usable, boss_phase=self.boss_phase)

        # Moderate state → fallback default weights
        weights = {
            "quick_slash":  40,
            "fireball":     20,
            "water_arrow":  20,
            "water_spell":  15,
            "rest":          5,
            "enrage":       25,
        }
        total_w = sum(weights.get(k, 10) for k in usable)
        snapshot = {k: round(weights.get(k, 10) / total_w, 4) for k in usable}
        pool = []
        for k in usable:
            pool.extend([k] * int(weights.get(k, 10)))
        act = random.choice(pool) if pool else "quick_slash"
        return act, snapshot

    # ── State check ──────────────────────────────────────────────────────────

    def check_state(self):
        if self.hp <= 0:
            self.hp   = 0
            self.life = 0
            self.state = "dead"

    # ── Computed properties ──────────────────────────────────────────────────

    @property
    def hp_percent(self):
        return self.hp / self.max_hp

    @property
    def xp_percent(self):
        return self.xp / 100

    @property
    def power_percent(self):
        return self.power / 100
