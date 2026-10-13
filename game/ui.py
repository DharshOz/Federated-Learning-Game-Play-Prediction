import pygame
import math
import os
import sys

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

try:
    from .entity import Entity
except (ImportError, ValueError):
    try:
        from entity import Entity
    except Exception:
        Entity = None


# ─── Color Palette ───────────────────────────────────────────────────────────
C_BG          = (10, 8, 20)
C_PANEL       = (20, 16, 38)
C_PANEL_DARK  = (12, 9, 25)
C_ACCENT      = (120, 60, 220)
C_GOLD        = (255, 200, 50)
C_WHITE       = (255, 255, 255)
C_LIGHT_GRAY  = (180, 175, 200)
C_GRAY        = (100, 95, 120)
C_RED         = (220, 50, 60)
C_GREEN       = (50, 200, 100)
C_BLUE        = (50, 140, 240)
C_YELLOW      = (240, 200, 40)
C_FIRE        = (255, 100, 30)
C_WATER       = (30, 160, 255)
C_SHADOW      = (0, 0, 0, 140)

ATTACK_COLORS = {
    "quick_slash": (200, 180, 255),
    "fireball":    (255, 100, 30),
    "water_arrow": (30, 180, 255),
    "water_spell": (60, 220, 200),
    "fire_spell":  (255, 60, 0),
    "heal":        (80, 220, 120),
    "enrage":      (255, 45, 65),
}

ATTACK_ICONS_COLOR = {
    "quick_slash": "⚔",
    "fireball":    "🔥",
    "water_arrow": "💧",
    "water_spell": "🌊",
    "fire_spell":  "☄",
    "heal":        "❤",
    "enrage":      "💢",
}


def draw_rounded_rect(surface, color, rect, radius=12, border=0, border_color=None):
    pygame.draw.rect(surface, color, rect, border_radius=radius)
    if border and border_color:
        pygame.draw.rect(surface, border_color, rect, border, border_radius=radius)


def glow_surface(size, color, alpha=80):
    """Create a radial-gradient glow surface."""
    surf = pygame.Surface(size, pygame.SRCALPHA)
    cx, cy = size[0] // 2, size[1] // 2
    max_r = min(cx, cy)
    for r in range(max_r, 0, -1):
        a = int(alpha * (1 - r / max_r))
        pygame.draw.circle(surf, (*color[:3], a), (cx, cy), r)
    return surf


class UI:
    def __init__(self, screen, fonts):
        self.screen = screen
        self.W, self.H = screen.get_size()
        self.fonts = fonts or {}    # dict: "title", "body", "small", "tiny"
        self._hover_states = {}     # btn_id -> float (0..1)
        self._pulse = 0.0           # global pulse tick

    # ─── Internal helpers ────────────────────────────────────────────────────

    def _get_font(self, name: str, fallback_size: int = 18):
        """Retrieve font by key, or fallback safely to a guaranteed Font object."""
        if hasattr(self, "fonts") and self.fonts and name in self.fonts and self.fonts[name] is not None:
            return self.fonts[name]
        try:
            return pygame.font.Font(None, fallback_size)
        except Exception:
            try:
                return pygame.font.SysFont("arial", fallback_size)
            except Exception:
                return None

    def _update_hover(self, btn_id, hovered, dt=16):
        cur = self._hover_states.get(btn_id, 0.0)
        target = 1.0 if hovered else 0.0
        speed = 0.08
        self._hover_states[btn_id] = cur + (target - cur) * speed * (dt / 16)

    def tick(self):
        self._pulse = (self._pulse + 0.04) % (2 * math.pi)

    # ─── Fancy RPG Button ────────────────────────────────────────────────────

    def draw_button(self, btn_id, label, rect, color=C_ACCENT,
                    mouse_pos=None, sub_label=None, icon_char=None):
        """Draw a stylised RPG button. Returns True if mouse is over it."""
        hovered = rect.collidepoint(mouse_pos) if mouse_pos else False
        self._update_hover(btn_id, hovered)
        h = self._hover_states.get(btn_id, 0.0)

        # Background
        base_col = tuple(min(255, int(c + h * 40)) for c in color)
        dark_col = tuple(max(0, int(c * 0.4)) for c in color)
        pygame.draw.rect(self.screen, dark_col, rect.inflate(4, 4), border_radius=14)
        pygame.draw.rect(self.screen, base_col, rect, border_radius=12)

        # Highlight (top edge shine)
        shine = pygame.Surface((rect.w, rect.h // 3), pygame.SRCALPHA)
        shine.fill((255, 255, 255, int(30 + h * 40)))
        shine_rect = shine.get_rect(topleft=rect.topleft)
        self.screen.blit(shine, shine_rect)

        # Border
        border_col = tuple(min(255, int(c + 80 + h * 60)) for c in color)
        pygame.draw.rect(self.screen, border_col, rect, 2, border_radius=12)

        # Text
        font = self._get_font("body", 18)
        if sub_label:
            txt = font.render(label, True, C_WHITE)
            sub_font = self._get_font("tiny", 12)
            sub = sub_font.render(sub_label, True, C_LIGHT_GRAY)
            ty = rect.centery - 12
            self.screen.blit(txt, txt.get_rect(centerx=rect.centerx, centery=ty))
            self.screen.blit(sub, sub.get_rect(centerx=rect.centerx, centery=ty + 20))
        else:
            txt = font.render(label, True, C_WHITE)
            self.screen.blit(txt, txt.get_rect(center=rect.center))

        return hovered

    # ─── Attack Button ───────────────────────────────────────────────────────

    def draw_attack_button(self, btn_id, attack_key, rect, hero,
                           mouse_pos=None, combo_chain=None):
        """Special button for combat attacks with cooldown/cost overlay."""
        hovered = rect.collidepoint(mouse_pos) if mouse_pos else False
        self._update_hover(btn_id, hovered)
        h = self._hover_states.get(btn_id, 0.0)

        # Lookup attack details
        current_entity = Entity
        if current_entity is None:
            return None

        info = current_entity.ATTACKS[attack_key]
        cd_cur = hero.cooldowns.get(attack_key, 0)
        on_cd  = cd_cur > 0
        can_afford = (hero.xp >= info["xp_cost"] and hero.power >= info["power_cost"])
        usable = (not on_cd) and can_afford

        # Combo highlight
        is_combo_next = False
        if combo_chain and not on_cd and can_afford:
            for cname, cdata in current_entity.COMBOS.items():
                seq = cdata["sequence"]
                if len(combo_chain) < len(seq):
                    if seq[:len(combo_chain)] == combo_chain and seq[len(combo_chain)] == attack_key:
                        is_combo_next = True
                        break

        color = ATTACK_COLORS.get(attack_key, C_ACCENT)
        if not usable:
            color = (50, 45, 60)
        elif is_combo_next:
            # Pulsing gold border
            p_val = (math.sin(self._pulse * 2) + 1) * 0.5
            color = tuple(min(255, int(c * 0.6 + 255 * p_val * 0.4)) for c in C_GOLD)

        # Background
        base_col = tuple(min(255, int(c + h * 30)) for c in color)
        pygame.draw.rect(self.screen, (10, 8, 18), rect.inflate(4, 4), border_radius=10)
        pygame.draw.rect(self.screen, base_col, rect, border_radius=8)

        # Border
        b_col = C_GOLD if is_combo_next else (
            tuple(min(255, int(c + 70)) for c in color) if usable else (70, 65, 80))
        b_width = 3 if is_combo_next else 2
        pygame.draw.rect(self.screen, b_col, rect, b_width, border_radius=8)

        # Attack name
        font = self._get_font("small", 14)
        name_col = C_WHITE if usable else C_GRAY
        txt = font.render(info["label"], True, name_col)
        self.screen.blit(txt, (rect.x + 10, rect.y + 7))

        # Cooldown / Cost badge
        tf = self._get_font("tiny", 11)
        if on_cd:
            cd_surf = tf.render(f"CD: {cd_cur}t", True, (255, 120, 80))
            self.screen.blit(cd_surf, (rect.right - cd_surf.get_width() - 8, rect.y + 8))
        else:
            cost_parts = []
            if info["xp_cost"] > 0:
                cost_parts.append(f"{info['xp_cost']} XP")
            if info["power_cost"] > 0:
                cost_parts.append(f"{info['power_cost']} P")
            if cost_parts:
                cost_str = " ".join(cost_parts)
                col = (100, 220, 255) if can_afford else (220, 80, 80)
                cost_surf = tf.render(cost_str, True, col)
                self.screen.blit(cost_surf, (rect.right - cost_surf.get_width() - 8, rect.y + 8))

        # Damage tag
        dmg_str = f"DMG {info['base_dmg']}" if info['base_dmg'] > 0 else info.get('type', '').upper()
        if attack_key == "rest":
            dmg_str = "RECHARGE"
        df = self._get_font("tiny", 11)
        d_surf = df.render(dmg_str, True, (180, 170, 200) if usable else (90, 85, 100))
        self.screen.blit(d_surf, (rect.x + 10, rect.bottom - 18))

        return hovered and usable

    # ─── HUDs ─────────────────────────────────────────────────────────────────

    def draw_hero_hud(self, hero, rect):
        """Draw left-side HUD for the player hero."""
        draw_rounded_rect(self.screen, C_PANEL, rect, radius=10, border=1, border_color=(60, 45, 90))

        # Name & Class
        f = self._get_font("body", 18)
        name_s = f.render(hero.name, True, C_GOLD)
        self.screen.blit(name_s, (rect.x + 12, rect.y + 8))

        # Health bar
        hp = getattr(hero, "hp", 100)
        max_hp = getattr(hero, "max_hp", 100)
        self._draw_bar(rect.x + 12, rect.y + 36, rect.w - 24, 16,
                       hp, max_hp, (40, 180, 80), (20, 80, 40), "HP")

        # XP bar
        xp = getattr(hero, "xp", 0)
        max_xp = getattr(hero, "max_xp", 100)
        self._draw_bar(rect.x + 12, rect.y + 58, rect.w - 24, 12,
                       xp, max_xp, (180, 120, 240), (70, 40, 100), "XP")

        # Power bar
        pwr = getattr(hero, "power", 0)
        max_pwr = getattr(hero, "max_power", 100)
        self._draw_bar(rect.x + 12, rect.y + 75, rect.w - 24, 12,
                       pwr, max_pwr, (240, 140, 40), (100, 50, 10), "PWR")

        # Status effect badges
        effects = getattr(hero, "status_effects", {})
        if not isinstance(effects, dict):
            effects = {}
        self._draw_status_badges(effects, rect.x + 12, rect.y + 92)

    def draw_villain_hud(self, villain, rect):
        """Draw right-side HUD for the boss/villain."""
        draw_rounded_rect(self.screen, C_PANEL, rect, radius=10, border=1, border_color=(90, 30, 40))

        # Name
        f = self._get_font("body", 18)
        name_s = f.render(getattr(villain, "name", "Boss"), True, (255, 90, 90))
        self.screen.blit(name_s, (rect.x + 12, rect.y + 8))

        # Health bar
        v_hp = getattr(villain, "hp", 100)
        v_max_hp = getattr(villain, "max_hp", 100)
        self._draw_bar(rect.x + 12, rect.y + 36, rect.w - 24, 16,
                       v_hp, v_max_hp, (220, 50, 60), (90, 20, 25), "HP")

        # Status effect badges
        v_effects = getattr(villain, "status_effects", {})
        if not isinstance(v_effects, dict):
            v_effects = {}
        self._draw_status_badges(v_effects, rect.x + 12, rect.y + 56)

    def _draw_bar(self, x, y, w, h, val, max_val, fg_col, bg_col, label=""):
        ratio = max(0.0, min(1.0, val / max(1, max_val)))
        pygame.draw.rect(self.screen, (20, 15, 30), (x, y, w, h), border_radius=4)
        pygame.draw.rect(self.screen, bg_col, (x, y, w, h), border_radius=4)
        fill_w = int(w * ratio)
        if fill_w > 0:
            pygame.draw.rect(self.screen, fg_col, (x, y, fill_w, h), border_radius=4)
            # Shine line
            shine = pygame.Surface((fill_w, h // 2), pygame.SRCALPHA)
            shine.fill((255, 255, 255, 45))
            self.screen.blit(shine, (x, y))
        pygame.draw.rect(self.screen, (60, 50, 80), (x, y, w, h), 1, border_radius=4)

        # Numeric text
        tf = self._get_font("tiny", 11)
        txt = tf.render(f"{label} {int(val)}/{int(max_val)}", True, C_WHITE)
        self.screen.blit(txt, (x + 6, y + (h - txt.get_height()) // 2))

    def _draw_status_badges(self, effects, x, y):
        badges = []
        if effects.get("burn", 0) > 0:
            badges.append((f"🔥 BURN {effects['burn']}t", (255, 90, 30)))
        if effects.get("exhaust", 0) > 0:
            badges.append((f"💨 EXHAUST {effects['exhaust']}t", (120, 160, 255)))
        if effects.get("weakened", 0) > 0:
            badges.append((f"💧 WEAK {effects['weakened']}t", (60, 220, 200)))
        if effects.get("shield", 0) > 0:
            badges.append((f"🛡 SHIELD {effects['shield']}t", (255, 200, 50)))

        tf = self._get_font("tiny", 10)
        cx = x
        for text, col in badges:
            s = tf.render(text, True, col)
            bw = s.get_width() + 8
            bh = 16
            pygame.draw.rect(self.screen, (15, 10, 25), (cx, y, bw, bh), border_radius=4)
            pygame.draw.rect(self.screen, col, (cx, y, bw, bh), 1, border_radius=4)
            self.screen.blit(s, (cx + 4, y + 2))
            cx += bw + 6

    # ─── Attack Panel ─────────────────────────────────────────────────────────

    def draw_attack_panel(self, hero, mouse_pos, panel_rect):
        """Draw the 7 attack buttons in a neat grid at the bottom-left."""
        draw_rounded_rect(self.screen, C_PANEL_DARK, panel_rect, radius=12,
                          border=2, border_color=C_ACCENT)

        current_entity = Entity
        if current_entity is None:
            return {}

        attacks = list(current_entity.ATTACKS.keys())
        btn_w, btn_h = 220, 42
        pad_x, pad_y = 12, 10
        cols = 2

        btn_rects = {}
        for i, atk_key in enumerate(attacks):
            col = i % cols
            row = i // cols
            bx = panel_rect.x + pad_x + col * (btn_w + 10)
            by = panel_rect.y + pad_y + row * (btn_h + 6)
            brect = pygame.Rect(bx, by, btn_w, btn_h)
            btn_rects[atk_key] = brect

            self.draw_attack_button(f"atk_{atk_key}", atk_key, brect, hero,
                                    mouse_pos=mouse_pos,
                                    combo_chain=getattr(hero, "combo_chain", []))

        return btn_rects

    # ─── Battle Log ──────────────────────────────────────────────────────────

    def draw_battle_log(self, log_lines, rect):
        """Draw scrolling combat event log at bottom right."""
        draw_rounded_rect(self.screen, (8, 6, 16, 210), rect, radius=10,
                          border=1, border_color=(60, 45, 80))
        tf = self._get_font("tiny", 11)
        max_lines = 6
        recent = log_lines[-max_lines:]
        y = rect.y + 8
        for i, line in enumerate(recent):
            alpha = int(120 + 135 * (i / max(1, len(recent) - 1)))
            col = (min(255, int(180 * alpha / 255)),
                   min(255, int(170 * alpha / 255)),
                   min(255, int(210 * alpha / 255)))
            surf = tf.render(line, True, col)
            self.screen.blit(surf, (rect.x + 10, y))
            y += 18

    def draw_floating_texts(self, float_texts, screen):
        """Draw, animate upwards, and fade out floating damage/status numbers."""
        tf = self._get_font("small", 14)
        bf = self._get_font("body", 16)
        alive = []
        for ft in float_texts:
            # Drift upward
            ft["y"] = ft.get("y", 0) - 1.2
            # Decay alpha / lifetime
            cur_alpha = ft.get("alpha", 255)
            ft["alpha"] = cur_alpha - 4

            if ft["alpha"] > 0:
                alive.append(ft)
                txt = str(ft.get("text", ""))
                font = bf if (txt.startswith("-") or txt.startswith("+") or "!" in txt) else tf
                col = ft.get("color", (255, 220, 50))
                surf = font.render(txt, True, col)
                if ft["alpha"] < 255:
                    surf.set_alpha(max(0, min(255, int(ft["alpha"]))))
                screen.blit(surf, (int(ft["x"]), int(ft["y"])))

        float_texts.clear()
        float_texts.extend(alive)

    # ─── Turn Banner ─────────────────────────────────────────────────────────

    def draw_turn_banner(self, text, color=C_GOLD):
        f = self._get_font("title", 24)
        surf = f.render(text, True, color)
        self.screen.blit(surf, surf.get_rect(center=(self.W // 2, 45)))

    # ─── Game Over / Win screen ───────────────────────────────────────────────

    def _get_sysfont(self, size: int = 14, bold: bool = False):
        """Retrieve a crisp system sans-serif font for detailed analysis text."""
        try:
            return pygame.font.SysFont("helvetica,arial,sans-serif", size, bold=bold)
        except Exception:
            return self._get_font("small", size)

    def _render_multiline(self, text: str, font, color, max_w: int, max_lines: int = 3):
        """Word-wrap text into rendered surfaces respecting max_w."""
        if not text:
            return []
        words = text.split()
        lines = []
        cur = ""
        for w in words:
            test = (cur + " " + w) if cur else w
            if font.size(test)[0] <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
                if len(lines) >= max_lines:
                    break
        if cur and len(lines) < max_lines:
            lines.append(cur)
        if len(lines) == max_lines and words:
            last = lines[-1]
            if font.size(last + "…")[0] <= max_w:
                lines[-1] = last + "…"
        return [font.render(l, True, color) for l in lines]

    def draw_endscreen(self, won, mouse_pos, prediction=None, agent_analysis=None):
        overlay = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 195))
        self.screen.blit(overlay, (0, 0))

        # Victory / Defeat Header
        msg = "⚔  VICTORY!  ⚔" if won else "💀  DEFEATED  💀"
        col = C_GOLD if won else C_RED
        f = self._get_font("title", 32)
        t = f.render(msg, True, col)
        self.screen.blit(t, t.get_rect(center=(self.W // 2, 70)))

        sub_f = self._get_font("body", 16)
        sub = sub_f.render(
            "You have triumphed over the boss!" if won else "The boss proved too formidable this time...",
            True, C_LIGHT_GRAY)
        self.screen.blit(sub, sub.get_rect(center=(self.W // 2, 102)))

        # ── AI Playstyle & Tactical Strategy Card ─────────────────────────────
        card_w, card_h = 960, 440
        card_x = self.W // 2 - card_w // 2
        card_y = 125
        card_rect = pygame.Rect(card_x, card_y, card_w, card_h)

        persona_name = (prediction.get("persona") if prediction else None) or "Optimal"
        badge_col = prediction.get("badge_color", C_ACCENT) if prediction else C_ACCENT
        title_text = prediction.get("title", "Adventurer") if prediction else "Tactician"
        desc_text = prediction.get("description", "Evaluating match decisions...") if prediction else "Analyzing combat decisions..."
        conf_pct = float(prediction.get("confidence_pct", 88.0) if prediction else 88.0)

        # Background panel & glowing border
        draw_rounded_rect(self.screen, (14, 10, 26), card_rect, radius=16, border=2, border_color=badge_col)

        # Header tag
        tag_f = self._get_font("tiny", 12)
        tag_left = tag_f.render("AI PLAYSTYLE CLASSIFICATION & STRATEGIC AGENT ANALYSIS", True, (190, 170, 240))
        self.screen.blit(tag_left, (card_x + 24, card_y + 16))

        tag_right = tag_f.render("FEDERATED GLOBAL MODEL v2.0", True, (6, 182, 212))
        self.screen.blit(tag_right, (card_x + card_w - tag_right.get_width() - 24, card_y + 16))

        # Main Playstyle Badge
        badge_f = self._get_font("body", 18)
        badge_str = f"ARCHETYPE: {title_text.upper()} [{persona_name.upper()} — {conf_pct:.1f}% MATCH]"
        badge_surf = badge_f.render(badge_str, True, badge_col)
        self.screen.blit(badge_surf, (card_x + 24, card_y + 42))

        # Description text
        body_font = self._get_sysfont(13)
        desc_lines = self._render_multiline(desc_text, body_font, (220, 215, 235), card_w - 48, max_lines=2)
        for idx, line_s in enumerate(desc_lines):
            self.screen.blit(line_s, (card_x + 24, card_y + 70 + idx * 18))

        # 4 Metrics Stat Boxes
        stats = prediction.get("key_stats", {}) if prediction else {}
        stat_items = [
            ("🛡️ Counter Rate", f"{stats.get('counter_rate', 0.0)}%", C_BLUE),
            ("⚔️ Damage Ratio", f"{stats.get('damage_trade_ratio', 1.0)}x", C_FIRE),
            ("🎲 Action Variety", f"{stats.get('action_entropy', 1.5)} bits", C_YELLOW),
            ("⚡ Reserves (P/XP)", f"{stats.get('avg_power', 0.0):.0f} / {stats.get('avg_xp', 0.0):.0f}", C_GREEN),
        ]

        bx_w, bx_h = 212, 54
        bx_y = card_y + 112
        for i, (label, val, clr) in enumerate(stat_items):
            bx_x = card_x + 24 + i * (bx_w + 20)
            b_rect = pygame.Rect(bx_x, bx_y, bx_w, bx_h)
            draw_rounded_rect(self.screen, (22, 17, 38), b_rect, radius=8, border=1, border_color=(65, 52, 95))

            lbl_s = tag_f.render(label, True, (160, 150, 190))
            self.screen.blit(lbl_s, lbl_s.get_rect(centerx=b_rect.centerx, y=b_rect.y + 8))

            val_f = self._get_font("small", 14)
            val_s = val_f.render(val, True, clr)
            self.screen.blit(val_s, val_s.get_rect(centerx=b_rect.centerx, y=b_rect.y + 28))

        # ── Dedicated Strategic Agent Analysis Panel ─────────────────────────
        agent = agent_analysis or {}
        agent_label = agent.get("playstyle_label") or persona_name
        agent_conf = agent.get("playstyle_confidence") or ("High" if conf_pct >= 80 else "Medium")
        agent_grade = agent.get("counter_play_grade") or ("A" if stats.get("counter_rate", 0) >= 70 else "B")
        agent_risk = agent.get("risk_profile") or "Calculated Balance"
        agent_reasoning = agent.get("playstyle_reasoning") or "Evaluated decision cadence, soft-counter reaction timing, and resource reserve behavior."
        agent_tip = agent.get("coaching_tip") or agent.get("agent_summary") or "Maintain reserves above 50 Power for active damage scaling."
        strengths = agent.get("strengths") or []

        panel_x = card_x + 18
        panel_y = card_y + 178
        panel_w = card_w - 36
        panel_h = 220
        panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

        draw_rounded_rect(self.screen, (20, 15, 36), panel_rect, radius=12, border=1, border_color=(140, 70, 230))

        # Panel Section Header
        hdr_surf = tag_f.render("🤖 TACTICAL AGENT STRATEGY ASSESSMENT", True, (215, 175, 255))
        self.screen.blit(hdr_surf, (panel_x + 14, panel_y + 10))

        # Badges row: Profile, Grade, Risk
        meta_f = self._get_sysfont(12, bold=True)
        meta_str = f"TACTICAL PROFILE: {agent_label} ({agent_conf})   •   COUNTER GRADE: {agent_grade}   •   RISK: {agent_risk}"
        meta_s = meta_f.render(meta_str, True, (6, 182, 212))
        self.screen.blit(meta_s, (panel_x + 14, panel_y + 32))

        # Reasoning Narrative
        lbl_r_surf = tag_f.render("TACTICAL REASONING:", True, (180, 160, 220))
        self.screen.blit(lbl_r_surf, (panel_x + 14, panel_y + 54))

        reasoning_lines = self._render_multiline(agent_reasoning, body_font, (240, 235, 255), panel_w - 28, max_lines=3)
        for idx, line_s in enumerate(reasoning_lines):
            self.screen.blit(line_s, (panel_x + 14, panel_y + 72 + idx * 18))

        # Strengths summary (if available)
        curr_y = panel_y + 72 + len(reasoning_lines) * 18 + 4
        if strengths:
            str_text = "KEY STRENGTHS: " + "  •  ".join(strengths[:2])
            str_s = self._get_sysfont(12).render(str_text, True, (160, 230, 180))
            self.screen.blit(str_s, (panel_x + 14, curr_y))
            curr_y += 20

        # Strategic Advice / Coaching Tip Box
        tip_box = pygame.Rect(panel_x + 10, curr_y + 2, panel_w - 20, 38)
        draw_rounded_rect(self.screen, (32, 22, 54), tip_box, radius=6, border=1, border_color=(168, 85, 247))
        tip_txt = f"💡 STRATEGIC ADVICE: {agent_tip}"
        tip_lines = self._render_multiline(tip_txt, self._get_sysfont(12, bold=True), (255, 245, 200), tip_box.w - 16, max_lines=2)
        for idx, t_line in enumerate(tip_lines):
            self.screen.blit(t_line, (tip_box.x + 8, tip_box.y + 4 + idx * 16))

        # Status Footer
        footer_f = self._get_font("tiny", 11)
        status_txt = footer_f.render("Tactical AI Agent: Synchronized  •  Match Telemetry: Transmitted to Federated Learning Hub", True, (110, 230, 150))
        self.screen.blit(status_txt, (card_x + 24, card_y + card_h - 22))

        # Retry / Dashboard / Menu buttons below the card
        btn_y = card_y + card_h + 15
        btn_w, btn_h = 220, 48
        gap = 20
        total_w = btn_w * 3 + gap * 2
        start_x = self.W // 2 - total_w // 2

        retry = pygame.Rect(start_x, btn_y, btn_w, btn_h)
        dash  = pygame.Rect(start_x + btn_w + gap, btn_y, btn_w, btn_h)
        menu  = pygame.Rect(start_x + (btn_w + gap) * 2, btn_y, btn_w, btn_h)

        self.endscreen_button_rects = (retry, dash, menu)

        self.draw_button("end_retry", "Play Again", retry,
                         color=C_GREEN, mouse_pos=mouse_pos)
        self.draw_button("end_dash",  "📊 Live Dashboard", dash,
                         color=(30, 130, 220), mouse_pos=mouse_pos)
        self.draw_button("end_menu",  "Main Menu",  menu,
                         color=C_ACCENT, mouse_pos=mouse_pos)
        return retry, dash, menu

    # ─── Tooltip ─────────────────────────────────────────────────────────────

    def draw_tooltip(self, attack_key, anchor_pos, hero=None):
        current_entity = Entity
        if current_entity is None:
            return

        a = current_entity.ATTACKS.get(attack_key)
        if not a:
            return

        cd_max = a.get("cooldown", 0)
        cd_cur = hero.cooldowns.get(attack_key, 0) if hero else 0

        lines = [
            (a["label"], C_GOLD),
            (a["desc"], C_WHITE),
            (f"Dmg: {a['base_dmg']}   Hit: {int(a['hit_chance']*100)}%", C_LIGHT_GRAY),
            (f"XP cost: {a['xp_cost']}   Power cost: {a['power_cost']}", C_LIGHT_GRAY),
        ]
        if cd_cur > 0:
            lines.append((f"⏳ On Cooldown: {cd_cur} turn(s) left", (255, 120, 60)))
        elif cd_max > 0:
            lines.append((f"Cooldown: {cd_max} turns after use", (180, 180, 220)))

        pad = 8
        sf = self._get_font("tiny", 12)
        surfaces = [sf.render(text, True, color) for text, color in lines]
        tw = max(s.get_width() for s in surfaces) + pad * 2
        th = sum(s.get_height() for s in surfaces) + pad * 2
        tx = min(anchor_pos[0], self.W - tw - 4)
        ty = max(4, anchor_pos[1] - th - 6)
        tip_rect = pygame.Rect(tx, ty, tw, th)
        draw_rounded_rect(self.screen, (20, 16, 40, 235), tip_rect, radius=8)
        pygame.draw.rect(self.screen, C_ACCENT, tip_rect, 1, border_radius=8)
        cy = ty + pad
        for s in surfaces:
            self.screen.blit(s, (tx + pad, cy))
            cy += s.get_height()

    # ─── Boss Telegraph ──────────────────────────────────────────────────────

    def draw_boss_intent(self, telegraphed_key, rect):
        """Draw the telegraphed boss intent banner / badge during player's turn."""
        if not telegraphed_key:
            return

        is_masked = (telegraphed_key in ("???", "unknown"))
        draw_rounded_rect(self.screen, (25, 15, 30), rect, radius=8, border=2,
                          border_color=(255, 60, 60) if not is_masked else (160, 120, 240))

        tf = self._get_font("tiny", 11)
        sub_s = tf.render("BOSS TELEGRAPH", True, (255, 120, 120) if not is_masked else (200, 170, 255))
        self.screen.blit(sub_s, (rect.x + 10, rect.y + 4))

        bf = self._get_font("small", 14)
        if is_masked:
            lbl = "??? (UNPREDICTABLE INTENT)"
            col = (200, 180, 255)
        else:
            current_entity = Entity
            lbl = current_entity.ATTACKS.get(telegraphed_key, {}).get("label", str(telegraphed_key).upper())
            col = (255, 200, 50)
        main_s = bf.render(lbl, True, col)
        self.screen.blit(main_s, (rect.x + 10, rect.y + 20))

    # ─── Selection Card ───────────────────────────────────────────────────────

    def draw_selection_card(self, btn_id, label, rect, thumbnail=None,
                             selected=False, mouse_pos=None):
        hovered = rect.collidepoint(mouse_pos) if mouse_pos else False
        self._update_hover(btn_id, hovered)
        h = self._hover_states.get(btn_id, 0.0)

        border_col = C_GOLD if selected else (
            tuple(min(255, int(c + h * 60)) for c in C_ACCENT))
        bg_col = (30, 24, 55) if selected else C_PANEL_DARK
        draw_rounded_rect(self.screen, bg_col, rect, radius=12)
        pygame.draw.rect(self.screen, border_col, rect, 2 + int(selected), border_radius=12)

        if thumbnail:
            tw = rect.w - 12
            th = rect.h - 30
            scaled = pygame.transform.scale(thumbnail, (tw, th))
            self.screen.blit(scaled, (rect.x + 6, rect.y + 4))

        sf = self._get_font("tiny", 12)
        lbl = sf.render(label, True, C_GOLD if selected else C_WHITE)
        self.screen.blit(lbl, lbl.get_rect(centerx=rect.centerx,
                                            bottom=rect.bottom - 4))
        if selected:
            ck = sf.render("✔", True, C_GOLD)
            self.screen.blit(ck, (rect.right - 18, rect.y + 4))

        return hovered

    # ─── Text Input Field ─────────────────────────────────────────────────────

    def draw_input_field(self, field_id: str, label: str, rect: pygame.Rect,
                         text: str, is_active: bool, placeholder: str = "",
                         mask: bool = False, mouse_pos=None) -> bool:
        """Draw an arcane-styled interactive text input box. Returns True if mouse hovered."""
        hovered = rect.collidepoint(mouse_pos) if mouse_pos else False
        self._update_hover(field_id, hovered)

        # Label above field
        if label:
            lf = self._get_font("tiny", 12)
            lbl_surf = lf.render(label, True, C_GOLD if is_active else C_LIGHT_GRAY)
            self.screen.blit(lbl_surf, (rect.x + 2, rect.y - 18))

        # Base background
        bg_col = (16, 12, 28) if not is_active else (24, 18, 42)
        pygame.draw.rect(self.screen, (8, 6, 14), rect.inflate(4, 4), border_radius=10)
        draw_rounded_rect(self.screen, bg_col, rect, radius=8)

        # Border color
        if is_active:
            p_val = (math.sin(self._pulse * 3) + 1) * 0.5
            border_col = (
                int(215 + 40 * p_val),
                int(170 + 35 * p_val),
                int(50 + 30 * p_val)
            )
            border_w = 2
        elif hovered:
            border_col = (170, 120, 245)
            border_w = 2
        else:
            border_col = (70, 60, 95)
            border_w = 1

        pygame.draw.rect(self.screen, border_col, rect, border_w, border_radius=8)

        # Inner text
        clip_rect = rect.inflate(-16, -10)
        font = self._get_font("body", 16)
        display_text = "●" * len(text) if mask else text

        if display_text:
            txt_surf = font.render(display_text, True, C_WHITE)
            if txt_surf.get_width() > clip_rect.w:
                self.screen.blit(txt_surf, (clip_rect.right - txt_surf.get_width(), clip_rect.centery - txt_surf.get_height() // 2))
            else:
                self.screen.blit(txt_surf, (clip_rect.x, clip_rect.centery - txt_surf.get_height() // 2))
        elif placeholder and not is_active:
            ph_surf = font.render(placeholder, True, (110, 100, 135))
            self.screen.blit(ph_surf, (clip_rect.x, clip_rect.centery - ph_surf.get_height() // 2))

        # Blinking cursor
        if is_active and (pygame.time.get_ticks() // 450) % 2 == 0:
            if display_text:
                txt_w = min(font.size(display_text)[0], clip_rect.w)
                cursor_x = clip_rect.x + txt_w + 2
            else:
                cursor_x = clip_rect.x + 2
            cursor_y1 = clip_rect.centery - 10
            cursor_y2 = clip_rect.centery + 10
            pygame.draw.line(self.screen, C_GOLD, (cursor_x, cursor_y1), (cursor_x, cursor_y2), 2)

        return hovered

