"""
ARCANE CLASH - 3D BOSS ROUND
Post-round-1 showdown with 3D animated characters rendered from FBX animations:
  - Mutant Flexing Muscles.fbx -> "taunt" & "idle" (flexing / starting battle stance)
  - Mutant Punch.fbx           -> "attack1" (powerful punch strike)
  - Jump Attack.fbx            -> "jump" (devastating leap slam attack)
  - Kick To The Groin.fbx      -> "dead" & "hurt" (faint / knockout collapse)

Features:
  - 3D-rendered character boss with multi-phase mechanics
  - Dynamic 6-action combat panel matching Round 1 efficiency:
    * Quick Slash (low cost, fast)
    * Fireball (burning burst)
    * Water Arrow (weakens boss next turn)
    * Heavy Strike (massive critical damage)
    * Heal (costs 0 Power, restores 25 HP & +15 Power)
    * Rest & Recharge (FREE, restores +20 XP, +25 Power, raises Shield)
  - Turn-by-turn passive Power & XP regeneration (never softlocks)
"""
from __future__ import annotations
import os
import sys
import random
import pygame

def _get_root() -> str:
    cur = os.path.dirname(os.path.abspath(__file__))
    while cur and os.path.dirname(cur) != cur:
        if os.path.exists(os.path.join(cur, ".env")) or os.path.exists(os.path.join(cur, "Assets")):
            return cur
        cur = os.path.dirname(cur)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

_ROOT = _get_root()
W, H = 1280, 720

C_GOLD   = (255, 200,  50)
C_WHITE  = (255, 255, 255)
C_RED    = (230,  50,  60)
C_GREEN  = ( 50, 215, 110)
C_BLUE   = ( 50, 160, 255)
C_ORANGE = (255, 140,  30)
C_GRAY   = (130, 125, 150)
C_BG     = (  8,   6,  18)

BOSS_DEFS = {
    "sentinel": {
        "name": "The Cyber Sentinel",
        "subtitle": "Titan 3D Automaton",
        "folder": "sentinel",
        "lore": [
            "Forged in 3D cyber-alloy, this Titan Automaton reads every move.",
            "Its cybernetic frame calculates perfect counters to defensive strategies.",
            "Optimal and Defensive fighters will find their shields tested to the limit.",
        ],
        "counters": ["Defensive", "Optimal"],
        "hp": 220,
        "atk": 16,
        "accent": (60, 190, 255),
        "bg_tint": (0, 30, 60, 130),
        "phase_msgs": [
            "PHASE 2 - Cyber Sentinel OVERDRIVE! Shields shattered!",
            "PHASE 3 - Sub-Zero Surge! Maximum output active!",
        ],
        "taunt_lines": [
            "Your tactics are obsolete against 3D kinetic force.",
            "Optimal? Then prepare for systematic destruction.",
            "I have shattered every champion before you.",
        ],
        "heavy_move": "Titan Jump Slam",
        "common_moves": ["Kinetic Punch", "Cyber Breaker", "Alloy Strike"],
    },
    "berserker": {
        "name": "Chaos Berserker",
        "subtitle": "Mutant 3D Warlord",
        "folder": "berserker",
        "lore": [
            "Born from primal chaos, this 3D Mutant Warlord feeds on sheer violence.",
            "It mirrors aggressive strikes tenfold and punishes careless fighters.",
            "Aggressive and Random fighters face an unpredictable beast of carnage.",
        ],
        "counters": ["Aggressive", "Random"],
        "hp": 200,
        "atk": 20,
        "accent": (255, 75, 75),
        "bg_tint": (60, 10, 0, 130),
        "phase_msgs": [
            "PHASE 2 - Berserker UNLEASHED! Primal frenzy!",
            "PHASE 3 - Blood Rage! Unstoppable onslaught!",
        ],
        "taunt_lines": [
            "Hit me harder! I FEED on aggression!",
            "Random strikes? You're already broken.",
            "Your spells are insect stings to mutant flesh.",
        ],
        "heavy_move": "Chaos Leap Slam",
        "common_moves": ["Savage Punch", "Feral Lunge", "Bone Breaker"],
    },
}

def _p(*parts):
    return os.path.join(_ROOT, *parts)

def _load_seq(folder: str, subfolder: str, scale: float = 0.82) -> list[pygame.Surface]:
    # 1. Prioritize real 3D rendered frames from FBX
    dir_3d = _p("assets_3d", folder, subfolder)
    if os.path.exists(dir_3d):
        files = sorted(f for f in os.listdir(dir_3d) if f.lower().endswith(".png"))
        frames = []
        for f in files:
            img = pygame.image.load(os.path.join(dir_3d, f)).convert_alpha()
            iw, ih = img.get_size()
            img = pygame.transform.scale(img, (max(1, int(iw * scale)), max(1, int(ih * scale))))
            frames.append(img)
        if frames:
            return frames

    # 2. Fallback to 2D villain sprites if 3D frames not present
    alt_folder = "Minotaur_02" if folder == "sentinel" else "Minotaur_03"
    base = _p("villans", "PNG", alt_folder, "PNG Sequences", subfolder)
    if not os.path.exists(base):
        return []
    files = sorted(f for f in os.listdir(base) if f.lower().endswith(".png"))
    frames = []
    for f in files:
        img = pygame.image.load(os.path.join(base, f)).convert_alpha()
        iw, ih = img.get_size()
        img = pygame.transform.scale(img, (max(1, int(iw * 0.55)), max(1, int(ih * 0.55))))
        img = pygame.transform.flip(img, True, False)
        frames.append(img)
    return frames

def load_boss_anims(folder: str, scale: float = 0.82) -> dict[str, list[pygame.Surface]]:
    def s(sub: str):
        return _load_seq(folder, sub, scale)

    anims = {}
    anims["idle"]    = s("idle") or s("Idle") or []
    anims["taunt"]   = s("taunt") or s("Taunt") or anims["idle"]
    anims["attack1"] = s("attack1") or s("Attacking") or anims["idle"]
    anims["jump"]    = s("jump") or anims["attack1"]
    anims["hurt"]    = s("hurt") or s("Hurt") or anims["idle"]
    anims["dead"]    = s("dead") or s("Dying") or anims["idle"]
    anims["walk"]    = anims["idle"]
    return anims

class BossSprite:
    def __init__(self, anims, default="idle", delay=85):
        self.anims = anims
        self.cur = default
        self.frame = 0
        self.delay = delay
        self._last = 0
        self.done = False
        self.loop = True
        self._q = None

    def play(self, name, loop=True, then=None):
        if name not in self.anims or not self.anims[name]:
            return
        if self.cur == name and self.loop == loop and not self.done:
            return
        self.cur = name
        self.frame = 0
        self.done = False
        self.loop = loop
        self._q = then

    def update(self, now):
        # Slightly faster playback for punch and jump strikes
        cur_delay = 65 if self.cur in ("attack1", "jump") else self.delay
        if now - self._last < cur_delay:
            return False
        self._last = now
        frames = self.anims.get(self.cur, [])
        if not frames:
            return False
        self.frame += 1
        if self.frame >= len(frames):
            if self.loop:
                self.frame = 0
            else:
                self.frame = len(frames) - 1
                self.done = True
                if self._q:
                    self.play(self._q, loop=True)
                    self._q = None
                    return True
        return False

    def surf(self):
        frames = self.anims.get(self.cur, [])
        return frames[min(self.frame, len(frames) - 1)] if frames else None

class BossEntity:
    def __init__(self, key):
        d = BOSS_DEFS[key]
        self.key = key
        self.name = d["name"]
        self.max_hp = d["hp"]
        self.hp = d["hp"]
        self.atk = d["atk"]
        self.accent = d["accent"]
        self.phase = 1
        self.is_dead = False
        self._moves = d["common_moves"]
        self._heavy = d["heavy_move"]
        self._taunts = d["taunt_lines"]
        self._phase_ms = d["phase_msgs"]

    def choose_attack(self, hero_hp, hero_max_hp):
        ratio = hero_hp / max(hero_max_hp, 1)
        h_chance = {1: 0.25, 2: 0.40, 3: 0.55}.get(self.phase, 0.25)
        if ratio < 0.35:
            h_chance += 0.20
        is_heavy = random.random() < h_chance
        return (self._heavy, True) if is_heavy else (random.choice(self._moves), False)

    def take_damage(self, dmg):
        self.hp = max(0, self.hp - dmg)
        if self.hp == 0:
            self.is_dead = True
            return None
        r = self.hp / self.max_hp
        if r <= 0.33 and self.phase < 3:
            self.phase = 3
            return self._phase_ms[1] if len(self._phase_ms) > 1 else "PHASE 3!"
        if r <= 0.60 and self.phase < 2:
            self.phase = 2
            return self._phase_ms[0]
        return None

    def attack(self, hero):
        move, is_heavy = self.choose_attack(hero.hp, hero.max_hp)
        hit = random.random() < (0.75 if is_heavy else 0.85)
        pm = {1: 1.0, 2: 1.25, 3: 1.45}.get(self.phase, 1.0)
        raw = int(self.atk * pm * random.uniform(0.90, 1.15))
        dmg = raw if is_heavy else int(raw * 0.72)
        return {"hit": hit, "dmg": dmg if hit else 0, "move": move, "is_heavy": is_heavy}

    def taunt(self):
        return random.choice(self._taunts)

class _Particle:
    def __init__(self, color):
        self.x = random.uniform(0, W)
        self.y = random.uniform(0, H)
        self.vx = random.uniform(-0.5, 0.5)
        self.vy = random.uniform(-1.2, -0.3)
        self.r = random.uniform(1.5, 3.5)
        self.a = random.randint(60, 180)
        self.color = color

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.a = max(0, self.a - 1)
        if self.y < -5 or self.a <= 0:
            self.__init__(self.color)

    def draw(self, surf):
        s = pygame.Surface((int(self.r * 2) + 2, int(self.r * 2) + 2), pygame.SRCALPHA)
        pygame.draw.circle(s, (*self.color[:3], self.a), (int(self.r) + 1, int(self.r) + 1), int(self.r))
        surf.blit(s, (int(self.x), int(self.y)))

class _FT:
    def __init__(self, text, x, y, color):
        self.text = text
        self.x = float(x)
        self.y = float(y)
        self.color = color
        self.a = 255
        self.vy = -1.5

    def update(self):
        self.y += self.vy
        self.a = max(0, self.a - 4)

    @property
    def done(self):
        return self.a <= 0

    def draw(self, surf, font):
        if self.done:
            return
        s = font.render(self.text, True, self.color)
        s.set_alpha(self.a)
        surf.blit(s, (int(self.x - s.get_width() // 2), int(self.y)))

def _hpbar(surf, rect, cur, mx, color, label, font):
    pygame.draw.rect(surf, (30, 25, 45), rect, border_radius=6)
    w = int(rect.w * max(0, cur / max(mx, 1)))
    if w > 0:
        pygame.draw.rect(surf, color, pygame.Rect(rect.x, rect.y, w, rect.h), border_radius=6)
    pygame.draw.rect(surf, (200, 190, 220), rect, 1, border_radius=6)
    t = font.render(f"{label}  {cur}/{mx}", True, C_WHITE)
    surf.blit(t, (rect.x, rect.y - 18))

# ── 6 CORE ACTIONS MATCHING ROUND 1 EFFICIENCY ──
BOSS_ACTIONS = [
    {
        "key": "slash",
        "label": "Quick Slash",
        "icon": "⚔️",
        "color": (200, 180, 255),
        "desc": "Fast strike. High accuracy, low resource cost.",
        "xp": 5,
        "pw": 5,
        "dmg": 14,
        "hit": 0.92,
        "heavy": False,
    },
    {
        "key": "fireball",
        "label": "Fireball",
        "icon": "🔥",
        "color": (255, 120, 40),
        "desc": "Blazing strike. Powerful flame burst.",
        "xp": 18,
        "pw": 18,
        "dmg": 30,
        "hit": 0.75,
        "heavy": False,
    },
    {
        "key": "water_arrow",
        "label": "Water Arrow",
        "icon": "💧",
        "color": (80, 190, 255),
        "desc": "Piercing arrow. Weakens boss attack by 40% next turn!",
        "xp": 12,
        "pw": 10,
        "dmg": 18,
        "hit": 0.85,
        "heavy": False,
    },
    {
        "key": "heavy",
        "label": "Heavy Strike",
        "icon": "💥",
        "color": C_ORANGE,
        "desc": "Devastating smash. Massive physical impact.",
        "xp": 20,
        "pw": 24,
        "dmg": 42,
        "hit": 0.70,
        "heavy": True,
    },
    {
        "key": "heal",
        "label": "Heal",
        "icon": "✨",
        "color": (80, 220, 120),
        "desc": "Recover 25 HP and restore +15 Power. Costs 0 Power!",
        "xp": 10,
        "pw": 0,
        "dmg": 0,
        "hit": 1.0,
        "heavy": False,
    },
    {
        "key": "rest",
        "label": "Rest & Recharge",
        "icon": "🛡️",
        "color": (255, 215, 60),
        "desc": "Skip attack. Gain +20 XP, +25 Power & Shield UP (50% block)!",
        "xp": 0,
        "pw": 0,
        "dmg": 0,
        "hit": 1.0,
        "heavy": False,
    },
]

class BossRound:
    S_SEL   = "select"
    S_INTRO = "intro"
    S_FIGHT = "fight"
    S_END   = "end"

    def __init__(self, screen, clock, fonts, backgrounds, hero, hero_sprite,
                 effects_lib, predicted_style=None):
        self.screen = screen
        self.clock = clock
        self.fonts = fonts
        self.bgs = backgrounds
        self.hero = hero
        self.hsp = hero_sprite
        self.effects = effects_lib
        self.predicted = predicted_style
        self._rec = self._recommend(predicted_style)
        self._state = self.S_SEL
        self.boss = None
        self.bsp = None
        self._bkey = None

        # Position coordinates
        self._hp = (310, H - 195)
        self._bp = (960, H - 170)

        self._intro_x = W + 200
        self._intro_ph = 0
        self._intro_until = 0
        self._villain_at = 0
        self._result_until = 0
        self._timed_at = 0
        self._banim_done = False
        self._hanim_done = False
        self._phase = "hero_turn"
        self._last_hr = {}
        self._last_br = {}
        self._log = []
        self._floats = []
        self._particles = []
        self._hov = None
        self.won = False

        # Strategic status effects
        self._hero_shielded = False
        self._boss_weakened = False

        f = lambda k, sz: fonts.get(k) or pygame.font.Font(None, sz)
        self._fT  = f("title", 32)
        self._fB  = f("body", 18)
        self._fS  = f("small", 15)
        self._fTi = f("tiny", 12)
        self._seed_p((120, 60, 220))

    @staticmethod
    def _recommend(style):
        if style in ("Defensive", "Optimal"):
            return "sentinel"
        if style in ("Aggressive", "Random"):
            return "berserker"
        return random.choice(["sentinel", "berserker"])

    def _seed_p(self, c, n=45):
        self._particles = [_Particle(c) for _ in range(n)]

    def _draw_p(self):
        for p in self._particles:
            p.update()
            p.draw(self.screen)

    def _log_m(self, m):
        self._log.append(m)
        if len(self._log) > 25:
            self._log = self._log[-25:]

    def _float(self, txt, x, y, c):
        self._floats.append(_FT(txt, x, y, c))

    def _bg(self, tint=None):
        if self.bgs:
            self.screen.blit(self.bgs[min(1, len(self.bgs) - 1)][1], (0, 0))
        else:
            self.screen.fill(C_BG)
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill(tint if tint else (0, 0, 0, 180))
        self.screen.blit(ov, (0, 0))

    def _rr(self, c, r, rad=12, bc=None, bw=0):
        pygame.draw.rect(self.screen, c, r, border_radius=rad)
        if bw and bc:
            pygame.draw.rect(self.screen, bc, r, bw, border_radius=rad)

    def _txt(self, font, text, color):
        return font.render(text, True, color)

    def _bc(self, s, cx, cy):
        self.screen.blit(s, s.get_rect(center=(cx, cy)))

    def _sel_rects(self):
        cw, gap = 340, 40
        x0 = W // 2 - (cw * 2 + gap + 120) // 2
        return {
            "sentinel": pygame.Rect(x0, 140, cw, 390),
            "berserker": pygame.Rect(x0 + cw + gap, 140, cw, 390),
            "ai": pygame.Rect(x0 + (cw + gap) * 2, 250, 120, 100),
        }

    def _arects(self):
        panel_w = W // 2 - 16
        n = len(BOSS_ACTIONS)
        bw = (panel_w - (n - 1) * 6) // n
        return {a["key"]: pygame.Rect(8 + i * (bw + 6), H - 118, bw, 108)
                for i, a in enumerate(BOSS_ACTIONS)}

    def _can_use(self, a):
        # Rest & Recharge is ALWAYS available
        if a["key"] == "rest":
            return True
        # Heal costs 0 Power
        if a["key"] == "heal":
            return self.hero.xp >= a["xp"]
        # Standard cost check
        return self.hero.xp >= a["xp"] and self.hero.power >= a["pw"]

    def run(self):
        running = True
        while running:
            self.clock.tick(60)
            now = pygame.time.get_ticks()
            mouse = pygame.mouse.get_pos()
            events = pygame.event.get()
            for e in events:
                if e.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
            if self._state == self.S_SEL:
                self._h_sel(events, mouse)
                self._d_sel(mouse)
            elif self._state == self.S_INTRO:
                self._h_intro(now)
                self._d_intro(now)
            elif self._state == self.S_FIGHT:
                self._h_fight(events, mouse, now)
                self._d_fight(mouse, now)
            elif self._state == self.S_END:
                self._h_end(events, mouse, now)
                self._d_end(mouse)
                if self._result_until > 0 and now >= self._result_until:
                    running = False
            pygame.display.flip()
        return self.won

    # ── SELECTION SCREEN ──
    def _h_sel(self, events, mouse):
        r = self._sel_rects()
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                for k in ("sentinel", "berserker", "ai"):
                    if r[k].collidepoint(mouse):
                        self._begin_intro(k if k != "ai" else self._rec)
                        return

    def _d_sel(self, mouse):
        self._bg()
        self._draw_p()
        t = self._txt(self._fT, "FINAL BOSS ROUND — 3D CHALLENGER", C_GOLD)
        self._bc(t, W // 2, 55)
        sub = self._txt(self._fS, "Challenge a 3D animated boss or let the AI adapt to your playstyle", C_GRAY)
        self._bc(sub, W // 2, 88)
        if self.predicted:
            rec_name = BOSS_DEFS[self._rec]["name"]
            rs = self._txt(self._fS, f"Your Playstyle: {self.predicted}  ->  Recommended: {rec_name}", (160, 220, 255))
            self._bc(rs, W // 2, 113)
        r = self._sel_rects()
        for k in ("sentinel", "berserker"):
            d = BOSS_DEFS[k]
            rc = r[k]
            hov = rc.collidepoint(mouse)
            bc = (28, 22, 55) if not hov else (45, 35, 85)
            bord = d["accent"] if (hov or k == self._rec) else (80, 70, 110)
            bw = 3 if (hov or k == self._rec) else 1
            self._rr(bc, rc, 16, bord, bw)
            if k == self._rec:
                badge = self._txt(self._fTi, "RECOMMENDED FOR YOUR PLAYSTYLE", C_GOLD)
                self.screen.blit(badge, badge.get_rect(centerx=rc.centerx, y=rc.y + 10))
            ns = self._txt(self._fB, d["name"], d["accent"])
            self.screen.blit(ns, ns.get_rect(centerx=rc.centerx, y=rc.y + 35))
            ss = self._txt(self._fTi, d["subtitle"], C_GRAY)
            self.screen.blit(ss, ss.get_rect(centerx=rc.centerx, y=rc.y + 58))
            pygame.draw.line(self.screen, (*d["accent"][:3], 120),
                             (rc.x + 20, rc.y + 78), (rc.right - 20, rc.y + 78), 1)
            ct = self._txt(self._fTi, "Counters: " + " & ".join(d["counters"]), C_RED)
            self.screen.blit(ct, ct.get_rect(centerx=rc.centerx, y=rc.y + 90))
            for i, line in enumerate(d["lore"]):
                lt = self._txt(self._fTi, line, (170, 160, 200))
                self.screen.blit(lt, lt.get_rect(centerx=rc.centerx, y=rc.y + 115 + i * 22))
            for j, (lbl, val) in enumerate([("HP", d["hp"]), ("ATK", d["atk"])]):
                pr = pygame.Rect(rc.x + 25 + j * 95, rc.y + 185, 80, 24)
                self._rr((50, 40, 80), pr, 8)
                pt = self._txt(self._fTi, f"{lbl}: {val}", C_WHITE)
                self.screen.blit(pt, pt.get_rect(center=pr.center))
            my = rc.y + 220
            self.screen.blit(self._txt(self._fTi, "Signature Moves:", C_GOLD), (rc.x + 20, my))
            for i, mv in enumerate(d["common_moves"]):
                self.screen.blit(self._txt(self._fTi, "* " + mv, (190, 180, 210)), (rc.x + 20, my + 20 + i * 18))
            hy = my + 80
            hv = self._txt(self._fTi, "Heavy: " + d["heavy_move"], C_ORANGE)
            self.screen.blit(hv, hv.get_rect(centerx=rc.centerx, y=hy))
            cta = pygame.Rect(rc.x + 30, rc.bottom - 50, rc.w - 60, 38)
            self._rr(d["accent"] if hov else (50, 40, 80), cta, 10)
            ct2 = self._txt(self._fS, "Challenge 3D Boss", C_WHITE)
            self.screen.blit(ct2, ct2.get_rect(center=cta.center))
        air = r["ai"]
        hova = air.collidepoint(mouse)
        self._rr((30, 60, 40) if hova else (20, 45, 28), air, 10, C_GREEN, 2)
        ai_t = self._txt(self._fS, "AI DECIDE", C_GREEN)
        self.screen.blit(ai_t, ai_t.get_rect(center=air.center))

    # ── INTRO SEQUENCE ──
    def _begin_intro(self, key):
        self._bkey = key
        d = BOSS_DEFS[key]
        self.boss = BossEntity(key)
        self.bsp = BossSprite(load_boss_anims(d["folder"]), "taunt", 85)
        self.bsp.play("taunt", loop=True)
        self._seed_p(d["accent"])
        self._state = self.S_INTRO
        self._intro_x = W + 200
        self._intro_ph = 0
        self._log = [f"  {self.boss.name} has entered the 3D Arena!", "Prepare your spells and strategy..."]
        self._log_m(self.boss.taunt())

    def _h_intro(self, now):
        if self._intro_ph == 0:
            self._intro_x = max(self._bp[0], self._intro_x - 8)
            if self._intro_x <= self._bp[0]:
                self._intro_ph = 1
                self.bsp.play("taunt", loop=False, then="idle")
                self._intro_until = now + 2800
        elif self._intro_ph == 1:
            self.bsp.update(now)
            if now >= self._intro_until:
                self._intro_ph = 2
                self._state = self.S_FIGHT
                self._phase = "hero_turn"
                self.bsp.play("idle", loop=True)
                self._restore_hp()
                self._log_m(f"Round 2: {self.boss.name} awaits — choose your attack!")

    def _restore_hp(self):
        # Restore player to healthy battle shape
        self.hero.hp = max(int(self.hero.max_hp * 0.85), self.hero.hp)
        self.hero.power = max(70, self.hero.power)
        self.hero.xp = max(50, self.hero.xp)
        self._hero_shielded = False
        self._boss_weakened = False

    def _d_intro(self, now):
        d = BOSS_DEFS[self._bkey]
        self._bg(d["bg_tint"])
        self._draw_p()
        if self.bsp:
            self.bsp.update(now)
            s = self.bsp.surf()
            if s:
                self.screen.blit(s, s.get_rect(midbottom=(int(self._intro_x), self._bp[1])))
        if self.hsp and hasattr(self.hsp, "get_surface"):
            hs = self.hsp.get_surface()
            if hs:
                self.screen.blit(hs, hs.get_rect(midbottom=self._hp))
        self._bc(self._txt(self._fT, "FINAL BOSS ROUND", C_GOLD), W // 2, 50)
        self._bc(self._txt(self._fT, self.boss.name, d["accent"]), W // 2, 90)
        self._bc(self._txt(self._fS, d["subtitle"], C_GRAY), W // 2, 120)
        for i, line in enumerate(d["lore"]):
            ls = self._txt(self._fTi, line, (180, 170, 210))
            self._bc(ls, W // 2, 150 + i * 20)
        self._d_log()

    # ── COMBAT LOOP ──
    def _h_fight(self, events, mouse, now):
        for ft in self._floats[:]:
            ft.update()
        self._floats = [f for f in self._floats if not f.done]

        if self._result_until > 0 and now >= self._result_until:
            self._result_until = 0
            self._state = self.S_END
            return

        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1 and self._phase == "hero_turn":
                for k, rc in self._arects().items():
                    if rc.collidepoint(mouse):
                        act = next((a for a in BOSS_ACTIONS if a["key"] == k), None)
                        if act and self._can_use(act):
                            self._hero_act(act, now)
                            break
            if e.type == pygame.MOUSEMOTION:
                self._hov = None
                for k, rc in self._arects().items():
                    if rc.collidepoint(mouse):
                        self._hov = k
                        break

        if self._phase == "hero_anim":
            if (self._timed_at > 0 and now >= self._timed_at) or self._hanim_done:
                self._timed_at = 0
                self._hanim_done = False
                r = self._last_hr
                if r.get("hit") and r.get("dmg", 0) > 0:
                    msg = self.boss.take_damage(r["dmg"])
                    self._float(f"-{r['dmg']}", self._bp[0], self._bp[1] - 160, C_RED)
                    if msg:
                        self._log_m(msg)
                        self._float(msg, self._bp[0], self._bp[1] - 220, C_ORANGE)
                elif not r.get("hit"):
                    self._float("MISS!", self._bp[0], self._bp[1] - 160, C_GRAY)
                if self.boss.is_dead:
                    self.bsp.play("dead", loop=False)
                    self._float("VICTORY!", W // 2, H // 2 - 60, C_GOLD)
                    self._log_m(f"You defeated {self.boss.name}!")
                    self.won = True
                    self._result_until = now + 3500
                    return
                self._phase = "villain_turn"
                self._villain_at = now + 850

        if self._phase == "villain_turn" and now >= self._villain_at:
            self._boss_act(now)

        if self._phase == "villain_anim" and self._banim_done:
            self._banim_done = False
            r = self._last_br
            if r.get("hit"):
                dmg = r["dmg"]
                if getattr(self, "_hero_shielded", False):
                    dmg = max(1, int(dmg * 0.50))
                    self._hero_shielded = False
                    self._float("BLOCKED 50%!", self._hp[0], self._hp[1] - 190, C_BLUE)
                if getattr(self, "_boss_weakened", False):
                    dmg = max(1, int(dmg * 0.60))
                    self._boss_weakened = False
                self.hero.hp = max(0, self.hero.hp - dmg)
                self._float(f"-{dmg}", self._hp[0], self._hp[1] - 160, C_RED)
                if hasattr(self.hsp, "play"):
                    self.hsp.play("hurt", loop=False, then="idle")
            else:
                self._float("DODGE!", self._hp[0], self._hp[1] - 160, C_GRAY)

            if self.hero.hp <= 0:
                if hasattr(self.hsp, "play"):
                    self.hsp.play("dead", loop=False)
                self._float("DEFEATED...", W // 2, H // 2 - 60, C_RED)
                self._log_m("You have fallen in the Boss Gauntlet...")
                self.won = False
                self._result_until = now + 3500
                return

            self._phase = "hero_turn"
            # Natural stamina and mana regeneration each turn (prevents softlocks!)
            self.hero.power = min(self.hero.max_power, self.hero.power + 6)
            self.hero.xp = min(self.hero.max_xp, self.hero.xp + 4)

    def _hero_act(self, a, now):
        self.hero.xp = max(0, self.hero.xp - a["xp"])
        self.hero.power = max(0, self.hero.power - a["pw"])
        self._phase = "hero_anim"

        if a["key"] == "rest":
            gain_xp = 20
            gain_pwr = 25
            self.hero.xp = min(self.hero.max_xp, self.hero.xp + gain_xp)
            self.hero.power = min(self.hero.max_power, self.hero.power + gain_pwr)
            self._hero_shielded = True
            self._last_hr = {"hit": True, "dmg": 0}
            self._float(f"+{gain_pwr} PWR  +{gain_xp} XP", self._hp[0], self._hp[1] - 160, C_GOLD)
            self._float("SHIELD UP!", self._hp[0], self._hp[1] - 195, C_BLUE)
            self._log_m(f"You Rest & Recharge: +{gain_xp} XP, +{gain_pwr} Power! Shield raised!")
            if hasattr(self.hsp, "play"):
                self.hsp.play("idle", loop=True)
            self._timed_at = now + 850
        elif a["key"] == "heal":
            h = min(25, self.hero.max_hp - self.hero.hp)
            self.hero.hp += h
            self.hero.power = min(self.hero.max_power, self.hero.power + 15)
            self._last_hr = {"hit": True, "dmg": 0}
            self._float(f"+{h} HP  +15 PWR", self._hp[0], self._hp[1] - 160, C_GREEN)
            self._log_m(f"You Heal for {h} HP and restore 15 Power!")
            if hasattr(self.hsp, "play"):
                self.hsp.play("idle", loop=True)
            self._timed_at = now + 850
        elif a["key"] == "water_arrow":
            hit = random.random() < a["hit"]
            raw = int(a["dmg"] * random.uniform(0.90, 1.20))
            if hasattr(self.hsp, "play"):
                self.hsp.play("attack1", loop=False, then="idle")
            self._last_hr = {"hit": hit, "dmg": raw if hit else 0}
            if hit:
                self._boss_weakened = True
                self._log_m(f"You: Water Arrow! Dealt {raw} dmg & WEAKENED boss!")
                self._float("WEAKENED!", self._bp[0], self._bp[1] - 200, C_BLUE)
            else:
                self._log_m(f"You: Water Arrow! MISSED!")
            self._timed_at = now + 1050
        else:
            hit = random.random() < a["hit"]
            raw = int(a["dmg"] * random.uniform(0.85, 1.20))
            if a["heavy"]:
                if hasattr(self.hsp, "play"):
                    self.hsp.play("attack2", loop=False, then="idle")
            else:
                if hasattr(self.hsp, "play"):
                    self.hsp.play("attack1", loop=False, then="idle")
            self._last_hr = {"hit": hit, "dmg": raw if hit else 0}
            self._log_m(f"You: {a['label']}! {'Dealt ' + str(raw) + ' dmg.' if hit else 'MISSED!'}")
            self._timed_at = now + 1050

    def _boss_act(self, now):
        r = self.boss.attack(self.hero)
        self._last_br = r
        self._phase = "villain_anim"
        if r.get("is_heavy"):
            self.bsp.play("jump", loop=False, then="idle")
        else:
            self.bsp.play("attack1", loop=False, then="idle")
        self._log_m(f"Boss: {r['move']}! {'Dealt ' + str(r['dmg']) + ' dmg.' if r['hit'] else 'MISSED!'}")

    def _d_fight(self, mouse, now):
        d = BOSS_DEFS[self._bkey]
        self._bg(d["bg_tint"])
        self._draw_p()

        if self.bsp and self.bsp.update(now):
            self._banim_done = True
        if self.hsp and hasattr(self.hsp, "update"):
            if self.hsp.update(now):
                self._hanim_done = True

        # Ground shadows
        for pos in [self._hp, self._bp]:
            sh = pygame.Surface((220, 26), pygame.SRCALPHA)
            pygame.draw.ellipse(sh, (0, 0, 0, 85), (0, 0, 220, 26))
            self.screen.blit(sh, (pos[0] - 110, pos[1] - 12))

        # Render 3D Boss & Hero sprites
        if self.bsp:
            bs = self.bsp.surf()
            if bs:
                self.screen.blit(bs, bs.get_rect(midbottom=self._bp))
        if self.hsp and hasattr(self.hsp, "get_surface"):
            hs = self.hsp.get_surface()
            if hs:
                self.screen.blit(hs, hs.get_rect(midbottom=self._hp))

        # Top HP / Resource Bars
        _hpbar(self.screen, pygame.Rect(12, 12, 270, 18), self.hero.hp, self.hero.max_hp, C_GREEN, self.hero.name, self._fTi)
        pygame.draw.rect(self.screen, (40, 30, 70), pygame.Rect(12, 40, 120, 10), border_radius=4)
        pygame.draw.rect(self.screen, C_BLUE, pygame.Rect(12, 40, int(120 * self.hero.xp / max(self.hero.max_xp, 1)), 10), border_radius=4)
        self.screen.blit(self._txt(self._fTi, f"XP {self.hero.xp}/{self.hero.max_xp}", C_BLUE), (138, 38))

        pygame.draw.rect(self.screen, (40, 30, 70), pygame.Rect(12, 55, 120, 10), border_radius=4)
        pygame.draw.rect(self.screen, C_ORANGE, pygame.Rect(12, 55, int(120 * self.hero.power / max(self.hero.max_power, 1)), 10), border_radius=4)
        self.screen.blit(self._txt(self._fTi, f"PWR {self.hero.power}/{self.hero.max_power}", C_ORANGE), (138, 53))

        # Shield badge on player
        if getattr(self, "_hero_shielded", False):
            sh_badge = self._txt(self._fTi, "🛡️ SHIELDED (-50% DMG)", C_GOLD)
            self.screen.blit(sh_badge, (12, 70))

        _hpbar(self.screen, pygame.Rect(W - 282, 12, 270, 18), self.boss.hp, self.boss.max_hp, d["accent"], self.boss.name, self._fTi)
        ph_c = {1: C_GREEN, 2: C_ORANGE, 3: C_RED}.get(self.boss.phase, C_WHITE)
        self.screen.blit(self._txt(self._fTi, f"Phase {self.boss.phase} — 3D Active", ph_c), (W - 282, 36))
        if getattr(self, "_boss_weakened", False):
            wk_badge = self._txt(self._fTi, "⚠️ WEAKENED (-40% ATK)", (120, 200, 255))
            self.screen.blit(wk_badge, (W - 282, 52))

        # Turn banner
        banners = {
            "hero_turn": ("YOUR TURN", C_GREEN),
            "hero_anim": ("Hero Attacking...", (200, 160, 255)),
            "villain_turn": ("3D BOSS TURN", C_RED),
            "villain_anim": ("3D Boss Strikes!", C_ORANGE),
        }
        bt, bc = banners.get(self._phase, ("", C_WHITE))
        if bt:
            self._bc(self._txt(self._fB, bt, bc), W // 2, 30)
        self._bc(self._txt(self._fTi, "FINAL BOSS ROUND — 3D GAUNTLET", C_GOLD), W // 2, 50)

        # ── ACTION PANEL WITH 6 RESPONSIVE BUTTONS ──
        if self._phase == "hero_turn":
            pan = pygame.Surface((W // 2, 130), pygame.SRCALPHA)
            pan.fill((14, 10, 28, 225))
            self.screen.blit(pan, (0, H - 130))
            pygame.draw.line(self.screen, (90, 70, 150), (0, H - 130), (W // 2, H - 130), 2)

            for a in BOSS_ACTIONS:
                rc = self._arects()[a["key"]]
                usable = self._can_use(a)
                hov = (self._hov == a["key"])
                bg = tuple(min(255, c // 4 + (45 if hov and usable else 0)) for c in a["color"])
                bs = pygame.Surface((rc.w, rc.h), pygame.SRCALPHA)
                pygame.draw.rect(bs, (*bg, 220 if usable else 70), (0, 0, rc.w, rc.h), border_radius=8)
                pygame.draw.rect(bs, (*a["color"], 220 if usable else 55), (0, 0, rc.w, rc.h), 2 if hov else 1, border_radius=8)
                self.screen.blit(bs, rc.topleft)

                ic = self._txt(self._fS, a["icon"], a["color"])
                self.screen.blit(ic, ic.get_rect(centerx=rc.centerx, y=rc.y + 6))

                lb = self._txt(self._fTi, a["label"], C_WHITE if usable else C_GRAY)
                self.screen.blit(lb, lb.get_rect(centerx=rc.centerx, y=rc.y + 32))

                # Cost label
                if a["key"] == "rest":
                    cost_str = "FREE"
                    cost_col = C_GREEN
                elif a["key"] == "heal":
                    cost_str = f"XP:{a['xp']} FREE"
                    cost_col = C_GREEN
                else:
                    cost_str = f"X:{a['xp']} P:{a['pw']}"
                    cost_col = C_WHITE if usable else (140, 130, 160)

                cs = self._txt(self._fTi, cost_str, cost_col)
                self.screen.blit(cs, cs.get_rect(centerx=rc.centerx, y=rc.y + 54))

                if hov and usable:
                    ts = self._txt(self._fTi, a["desc"], (235, 230, 255))
                    tr = ts.get_rect(midbottom=(rc.centerx, rc.y - 8))
                    bg2 = pygame.Surface((tr.w + 16, tr.h + 8), pygame.SRCALPHA)
                    bg2.fill((20, 15, 45, 220))
                    self.screen.blit(bg2, (tr.x - 8, tr.y - 4))
                    self.screen.blit(ts, tr)

        self._d_log()
        for ft in self._floats:
            ft.draw(self.screen, self._fB)

    def _d_log(self):
        lp = pygame.Rect(W // 2 + 5, H - 130, W // 2 - 5, 125)
        ls = pygame.Surface((lp.w, lp.h), pygame.SRCALPHA)
        ls.fill((10, 8, 22, 215))
        self.screen.blit(ls, lp.topleft)
        pygame.draw.rect(self.screen, (90, 70, 150), lp, 1, border_radius=6)
        y = lp.y + 6
        for line in self._log[-6:]:
            lt = self._txt(self._fTi, line[:72], (195, 190, 225))
            self.screen.blit(lt, (lp.x + 8, y))
            y += 18
            if y > lp.bottom - 4:
                break

    # ── END SCREEN ──
    def _h_end(self, events, mouse, now):
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN:
                self._result_until = now

    def _d_end(self, mouse):
        d = BOSS_DEFS[self._bkey]
        self._bg(d["bg_tint"])
        self._draw_p()
        if self.bsp:
            bs = self.bsp.surf()
            if bs:
                self.screen.blit(bs, bs.get_rect(midbottom=self._bp))
        if self.hsp and hasattr(self.hsp, "get_surface"):
            hs = self.hsp.get_surface()
            if hs:
                self.screen.blit(hs, hs.get_rect(midbottom=self._hp))
        card = pygame.Rect(W // 2 - 300, H // 2 - 180, 600, 360)
        cs = pygame.Surface((card.w, card.h), pygame.SRCALPHA)
        cs.fill((14, 10, 28, 235))
        self.screen.blit(cs, card.topleft)
        pygame.draw.rect(self.screen, C_GOLD if self.won else C_RED, card, 3, border_radius=16)
        if self.won:
            title, col, msg, sub = "3D BOSS DEFEATED!", C_GOLD, f"You overcame {self.boss.name}!", "The realm celebrates your triumph in the gauntlet!"
        else:
            title, col, msg, sub = "GAUNTLET DEFEAT...", C_RED, f"{self.boss.name} proved too powerful.", "Refine your strategy and return."
        self._bc(self._txt(self._fT, title, col), W // 2, card.y + 55)
        self._bc(self._txt(self._fB, msg, C_WHITE), W // 2, card.y + 100)
        self._bc(self._txt(self._fS, sub, C_GRAY), W // 2, card.y + 130)
        for i, st in enumerate([f"Boss HP Left: {self.boss.hp}/{self.boss.max_hp}",
                                f"Your HP Left: {self.hero.hp}/{self.hero.max_hp}",
                                f"3D Boss Phase Reached: {self.boss.phase}"]):
            sv = self._txt(self._fTi, st, (180, 175, 210))
            self._bc(sv, W // 2, card.y + 170 + i * 22)
        self._bc(self._txt(self._fTi, "(Click anywhere to view Final Strategic Analysis)", C_GRAY), W // 2, card.bottom - 30)

def launch_boss_round(screen, clock, fonts, backgrounds, hero, hero_sprite,
                      effects_lib, predicted_style=None):
    """Launch the Boss Round. Returns True if hero wins."""
    br = BossRound(screen, clock, fonts, backgrounds, hero, hero_sprite,
                   effects_lib, predicted_style)
    return br.run()
