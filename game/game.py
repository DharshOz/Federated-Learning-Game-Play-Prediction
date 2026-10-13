"""
╔══════════════════════════════════════════════════════════════════╗
║            ARCANE CLASH  –  Turn-Based Wizard RPG                ║
║  Heroes: Fire Wizard | Lightning Mage | Wanderer Magician         ║
║  Villains: Minotaur Ⅰ | Minotaur Ⅱ | Minotaur Ⅲ (random)       ║
╚══════════════════════════════════════════════════════════════════╝
"""

import pygame
import sys
import os
import random
import math
import traceback

# ─── project root and imports ───────────────────────────────────────────────
def get_project_root() -> str:
    cur = os.path.dirname(os.path.abspath(__file__))
    while cur and os.path.dirname(cur) != cur:
        if os.path.exists(os.path.join(cur, "Assets")) or os.path.exists(os.path.join(cur, ".env")):
            return cur
        cur = os.path.dirname(cur)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

BASE = get_project_root()
if BASE not in sys.path:
    sys.path.insert(0, BASE)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, ".env"))
except Exception:
    pass

try:
    from .entity import Entity
    from .ui import UI, C_WHITE, C_RED, C_GOLD, C_GREEN, C_ACCENT, C_BLUE, C_LIGHT_GRAY, glow_surface
    from .animation import AnimatedSprite, EffectAnimation, load_sequence, load_spritesheet_row
    from .logger import BattleLogger
    from .adaptive_weighting import AdaptiveBossMemory
    from .auth_manager import get_auth_manager
except (ImportError, ValueError):
    from entity import Entity
    from ui import UI, C_WHITE, C_RED, C_GOLD, C_GREEN, C_ACCENT, C_BLUE, C_LIGHT_GRAY, glow_surface
    from animation import AnimatedSprite, EffectAnimation, load_sequence, load_spritesheet_row
    from logger import BattleLogger
    from adaptive_weighting import AdaptiveBossMemory
    from auth_manager import get_auth_manager

import atexit

try:
    from backend.server_manager import ensure_server_running, open_dashboard
except Exception:
    ensure_server_running = lambda: None
    open_dashboard = lambda: None

# Boss Round (post-round-1 gauntlet with 3D-character-inspired bosses)
try:
    from .boss_round import launch_boss_round
except (ImportError, ValueError):
    try:
        from boss_round import launch_boss_round
    except ImportError:
        launch_boss_round = None

try:
    from backend.client_sync import get_client_sync
    from game.logger import get_active_player_id
except Exception:
    get_client_sync = None
    get_active_player_id = None

def _cleanup_offline():
    try:
        if get_client_sync and get_active_player_id:
            pid = get_active_player_id()
            if pid:
                get_client_sync().send_disconnect(pid)
    except Exception:
        pass

atexit.register(_cleanup_offline)

# ═══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════
W, H = 1280, 720
FPS  = 60


def path(*parts):
    return os.path.join(BASE, *parts)


# ═══════════════════════════════════════════════════════════════════════════════
#  ASSET LOADERS
# ═══════════════════════════════════════════════════════════════════════════════

def load_fonts():
    font_path = path("Assets", "fonts", "joystix_monospace.otf")
    if os.path.exists(font_path):
        try:
            return {
                "title": pygame.font.Font(font_path, 32),
                "body":  pygame.font.Font(font_path, 18),
                "small": pygame.font.Font(font_path, 15),
                "tiny":  pygame.font.Font(font_path, 12),
            }
        except Exception:
            pass
    return {
        "title": pygame.font.Font(None, 32),
        "body":  pygame.font.Font(None, 18),
        "small": pygame.font.Font(None, 15),
        "tiny":  pygame.font.Font(None, 12),
    }


def load_backgrounds():
    """Returns list of (name, surface) tuples for all backgrounds."""
    bgs = []
    for folder in ["1", "2", "3", "4", "5", "6", "7", "8"]:
        big = path("backgrounds", folder, "2304x1296.png")
        if os.path.exists(big):
            img = pygame.image.load(big).convert()
            img = pygame.transform.scale(img, (W, H))
            bgs.append((f"Stage {folder}", img))
    # original city background as bonus
    orig = path("Assets", "background", "city1.png")
    if os.path.exists(orig):
        img = pygame.image.load(orig).convert()
        img = pygame.transform.scale(img, (W, H))
        bgs.append(("City", img))
    return bgs


def load_hero_anims(hero_folder, frame_w=128, frame_h=128, scale=2):
    """Load wizard hero animations from separate PNG spritesheets."""
    p = path("wizards heros", hero_folder)
    anims = {}

    def load_sheet(filename, h=frame_h):
        fp = os.path.join(p, filename)
        if not os.path.exists(fp):
            return []
        img = pygame.image.load(fp).convert_alpha()
        iw, ih = img.get_size()
        n = iw // frame_w
        frames = []
        for i in range(n):
            surf = pygame.Surface((frame_w, h), pygame.SRCALPHA)
            surf.blit(img, (0, 0), (i * frame_w, 0, frame_w, h))
            surf = pygame.transform.scale(surf, (frame_w * scale, h * scale))
            frames.append(surf)
        return frames

    anims["idle"]     = load_sheet("Idle.png")     or load_sheet("Walk.png")
    anims["attack1"]  = load_sheet("Attack_1.png")
    anims["attack2"]  = load_sheet("Attack_2.png")
    anims["hurt"]     = load_sheet("Hurt.png")
    anims["dead"]     = load_sheet("Dead.png")
    anims["run"]      = load_sheet("Run.png")      or anims["idle"]

    # Charge / special (some heroes have it)
    charge = load_sheet("Charge.png", h=64) or load_sheet("Charge_1.png", h=64)
    anims["charge"]   = charge if charge else anims["idle"]

    return anims


def load_villain_anims(villain_folder, scale=0.5):
    """Load villain PNG-sequence animations."""
    base = path("villans", "PNG", villain_folder, "PNG Sequences")
    anims = {}

    def load_seq(sub):
        folder = os.path.join(base, sub)
        if not os.path.exists(folder):
            return []
        files = sorted(f for f in os.listdir(folder) if f.endswith(".png"))
        frames = []
        for f in files:
            img = pygame.image.load(os.path.join(folder, f)).convert_alpha()
            iw, ih = img.get_size()
            nw, nh = int(iw * scale), int(ih * scale)
            img = pygame.transform.scale(img, (nw, nh))
            # Flip horizontally so villain faces left (toward hero)
            img = pygame.transform.flip(img, True, False)
            frames.append(img)
        return frames

    anims["idle"]    = load_seq("Idle") or load_seq("Idle Blink")
    anims["attack1"] = load_seq("Attacking")
    anims["hurt"]    = load_seq("Hurt")
    anims["dead"]    = load_seq("Dying")
    anims["taunt"]   = load_seq("Taunt") or anims["idle"]
    return anims


def load_effects():
    """Load spell/attack effects as lists of frames."""
    effects = {}

    def load_eff(folder, prefix, ext=".png"):
        p = path("attack effects", folder, "PNG")
        if not os.path.exists(p):
            return []
        files = sorted(f for f in os.listdir(p) if f.endswith(ext))
        return [pygame.image.load(os.path.join(p, f)).convert_alpha()
                for f in files]

    effects["fire_ball"]   = load_eff("Fire Ball",   "Fire Ball")
    effects["fire_arrow"]  = load_eff("Fire Arrow",  "Fire Arrow")
    effects["fire_spell"]  = load_eff("Fire Spell",  "Fire Spell")
    effects["water_ball"]  = load_eff("Water Ball",  "Water Ball")
    effects["water_arrow"] = load_eff("Water Arrow", "Water Arrow")
    effects["water_spell"] = load_eff("Water Spell", "Water Spell")
    return effects


# Map attack_key -> spell effect to show
ATTACK_EFFECT_MAP = {
    "quick_slash": "fire_arrow",
    "fireball":    "fire_ball",
    "water_arrow": "water_arrow",
    "water_spell": "water_spell",
    "fire_spell":  "fire_spell",
    "heal":        None,
    "rest":        None,      # no projectile for rest
    "enrage":      "fire_spell",
}

# Map attack_key -> hero sprite animation
ATTACK_ANIM_MAP = {
    "quick_slash": "attack1",
    "fireball":    "attack2",
    "water_arrow": "attack1",
    "water_spell": "attack2",
    "fire_spell":  "charge",
    "heal":        "idle",
    "rest":        "idle",    # rest plays idle, uses timer not animation done
    "enrage":      "attack1",
}

# Attacks that skip animation-done wait and use a fixed timer instead
TIMED_ACTIONS = {"rest", "heal"}


# ═══════════════════════════════════════════════════════════════════════════════
#  GAME STATES
# ═══════════════════════════════════════════════════════════════════════════════
STATE_LOGIN       = "login"
STATE_MENU        = "menu"
STATE_SELECT      = "select"
STATE_COMBAT      = "combat"
STATE_GAMEOVER    = "gameover"
STATE_BOSS_ROUND  = "boss_round"    # Post-round-1 boss gauntlet

PHASE_HERO_TURN   = "hero_turn"
PHASE_HERO_ANIM   = "hero_anim"
PHASE_EFFECT      = "effect"
PHASE_VILLAIN_ANIM= "villain_anim"
PHASE_VILLAIN_TURN= "villain_turn"
PHASE_RESULT      = "result"


# ═══════════════════════════════════════════════════════════════════════════════
#  HERO DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════
HEROES = [
    {
        "name":   "Fire Wizard",
        "folder": "Fire Wizard",
        "hp":     120,
        "atk":    14,
        "desc":   "High damage, fire mastery.\nWeak after heavy spells.",
        "thumb":  "Idle.png",
    },
    {
        "name":   "Lightning Mage",
        "folder": "Lightning Mage",
        "hp":     100,
        "atk":    16,
        "desc":   "Lightning-fast attacks.\nLow HP but high accuracy.",
        "thumb":  "Idle.png",
    },
    {
        "name":   "Wanderer",
        "folder": "Wanderer Magican",
        "hp":     110,
        "atk":    12,
        "desc":   "Balanced mage.\nVersatile and resilient.",
        "thumb":  "Idle.png",
    },
]

VILLAIN_FOLDERS = ["Minotaur_01", "Minotaur_02", "Minotaur_03"]
VILLAIN_NAMES   = ["Minotaur I", "Minotaur II", "Minotaur III"]


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN GAME CLASS
# ═══════════════════════════════════════════════════════════════════════════════
class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("Arcane Clash")
        self.clock = pygame.time.Clock()
        self.running = True

        self.fonts     = load_fonts()
        self.ui        = UI(self.screen, self.fonts)
        self.backgrounds = load_backgrounds()
        self.effects_lib = load_effects()
        self.effects     = self.effects_lib

        # Selection state
        self.selected_hero_idx = 0
        self.selected_bg_idx   = 0

        # Combat state
        self.hero    = None
        self.villain = None
        self.hero_sprite    = None
        self.villain_sprite = None
        self.active_effects = []   # list of EffectAnimation
        self.float_texts    = []   # floating damage numbers
        self.battle_log     = []
        self.phase          = PHASE_HERO_TURN
        self.won            = False

        # Animation-done flags: set True by draw (update), read by handle
        self._hero_anim_finished    = False
        self._villain_anim_finished = False
        # Gameover timer: non-zero means waiting to switch state
        self._gameover_at  = 0
        # Timed-action delay (rest/heal use a countdown instead of animation-done)
        self._timed_action_at = 0

        # Pending attack (set when hero picks an action)
        self.pending_hero_attack    = None
        self.pending_villain_attack = None

        # Safe defaults so PHASE_RESULT never crashes on first-turn death
        _no_result = {"hit": False, "dmg": 0, "effect_msg": "", "attack_key": None}
        self._last_hero_result    = dict(_no_result)
        self._last_villain_result = dict(_no_result)

        # Hero / Villain screen positions (midbottom of sprite)
        self.hero_pos    = (310, H - 195)
        self.villain_pos = (960, H - 200)

        # Tooltip tracking
        self.hovered_attack = None

        # Compounding Strategic Depth & Playstyle Logging state
        self.logger = BattleLogger()
        self.adaptive_memory = AdaptiveBossMemory()
        self.turn_number = 1
        self.hero_turn_started_at = 0
        self.boss_telegraphed_act = None
        self.boss_actual_act = None
        self.boss_is_feint = False
        self.latest_adaptive_weights = {}
        self.player_action_history = []
        self.quick_slash_streak = 0
        self.boss_phase = 1
        self.phase2_boss_turns_count = 0
        self.last_phase_transition_occurred = False
        self._dashboard_opened_for_match = False
        self._boss_round_triggered = False   # True once boss round fires per match

        # Automatically start backend observatory server in background
        try:
            ensure_server_running()
        except Exception as e:
            print(f"[Game] Server auto-start note: {e}")

        # Load thumbnails for selection screen
        self.hero_thumbs = []
        for h in HEROES:
            fp = path("wizards heros", h["folder"], h["thumb"])
            if os.path.exists(fp):
                img = pygame.image.load(fp).convert_alpha()
                # Extract first frame 128x128
                frame = pygame.Surface((128, 128), pygame.SRCALPHA)
                frame.blit(img, (0, 0), (0, 0, 128, 128))
                self.hero_thumbs.append(frame)
            else:
                self.hero_thumbs.append(None)

        self.bg_thumbs = []
        for _, bg in self.backgrounds:
            thumb = pygame.transform.scale(bg, (160, 90))
            self.bg_thumbs.append(thumb)

        # Authentication & Player Identity State
        self.auth = get_auth_manager()
        self.login_username = ""
        self.login_password = ""
        self.login_mode = "login"  # "login" | "register"
        self.login_active_field = "username"
        self.login_show_password = False
        self.login_status_msg = ""
        self.login_status_color = C_WHITE

        # Set initial screen state & player identity
        if self.auth.is_logged_in():
            self.state = STATE_MENU
            uname = self.auth.get_username()
            self.logger.set_player(uname)
            try:
                if get_client_sync:
                    get_client_sync().start_heartbeat_loop(uname, hero_class="Lobby")
            except Exception:
                pass
        else:
            self.state = STATE_LOGIN

        # Particles / background overlay
        self.particles = []
        self._init_particles()

    # ─── PARTICLES ────────────────────────────────────────────────────────────

    def _init_particles(self):
        for _ in range(40):
            self.particles.append(self._new_particle())

    def _new_particle(self):
        return {
            "x": random.uniform(0, W),
            "y": random.uniform(0, H),
            "vy": random.uniform(-0.3, -0.8),
            "vx": random.uniform(-0.2, 0.2),
            "size": random.uniform(1, 3),
            "alpha": random.randint(30, 120),
            "color": random.choice([(180, 100, 255), (80, 160, 255), (255, 160, 60)]),
        }

    def _update_draw_particles(self):
        for p in self.particles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            if p["y"] < -5 or p["x"] < -5 or p["x"] > W + 5:
                p.update(self._new_particle())
            surf = pygame.Surface((int(p["size"] * 2), int(p["size"] * 2)),
                                   pygame.SRCALPHA)
            pygame.draw.circle(surf, (*p["color"], p["alpha"]),
                               (int(p["size"]), int(p["size"])), int(p["size"]))
            self.screen.blit(surf, (int(p["x"]), int(p["y"])))

    # ─── COMBAT SETUP ─────────────────────────────────────────────────────────

    def start_combat(self):
        hd = HEROES[self.selected_hero_idx]
        self.hero = Entity(hd["name"], hd["hp"], hd["atk"], "hero")
        hero_anims = load_hero_anims(hd["folder"], scale=2)
        self.hero_sprite = AnimatedSprite(hero_anims, "idle", frame_delay=100)

        vill_idx = random.randint(0, 2)
        vf = VILLAIN_FOLDERS[vill_idx]
        vn = VILLAIN_NAMES[vill_idx]
        self.villain = Entity(vn, 130, 12, "villain")
        villain_anims = load_villain_anims(vf, scale=0.55)
        self.villain_sprite = AnimatedSprite(villain_anims, "idle", frame_delay=100)

        self.phase = PHASE_HERO_TURN
        self.active_effects.clear()
        self.float_texts.clear()
        player_ident = self.auth.get_username() or "Champion"
        self.battle_log = [f"{player_ident} [{self.hero.name}] vs {self.villain.name}!",
                            "Choose your attack wisely..."]
        self.pending_hero_attack    = None
        self.pending_villain_attack = None
        self._hero_anim_finished    = False
        self._villain_anim_finished = False
        self._gameover_at           = 0
        self._timed_action_at       = 0
        _no_result = {"hit": False, "dmg": 0, "effect_msg": "", "attack_key": None}
        self._last_hero_result    = dict(_no_result)
        self._last_villain_result = dict(_no_result)

        # Compounding Strategic Depth setup: initial boss telegraph & logging
        self.turn_number = 1
        self.boss_phase = 1
        self.villain.boss_phase = 1
        self.phase2_boss_turns_count = 0
        self.last_phase_transition_occurred = False
        self.player_action_history = []
        self.quick_slash_streak = 0
        self.adaptive_memory.reset()
        self._dashboard_opened_for_match = False
        self._boss_round_triggered = False

        self.boss_telegraphed_act, self.boss_actual_act, self.boss_is_feint, self.latest_adaptive_weights = (
            self.villain.plan_next_attack(adaptive_memory=self.adaptive_memory)
        )
        self.hero_turn_started_at = pygame.time.get_ticks()
        self.logger.start_match(self.hero.name, self.villain.name, self.hero.max_hp)
        self.logger.mark_turn_start()

        telegraphed_label = Entity.ATTACKS[self.boss_telegraphed_act]["label"]
        self.log(f"⚠️ {self.villain.name} is preparing {telegraphed_label}!")

        self.state = STATE_COMBAT

    # ─── ADD EFFECT ───────────────────────────────────────────────────────────

    def spawn_effect(self, effect_key, target_pos, scale=0.18):
        frames = self.effects_lib.get(effect_key, [])
        if frames:
            eff = EffectAnimation(frames, target_pos, scale=scale, frame_delay=55)
            self.active_effects.append(eff)

    def spawn_float(self, text, pos, color=(255, 220, 50)):
        self.float_texts.append({
            "text": text, "x": pos[0] - 20, "y": pos[1],
            "alpha": 255, "color": color,
        })

    # ─── BATTLE LOG HELPER ────────────────────────────────────────────────────

    def log(self, msg):
        self.battle_log.append(msg)
        if len(self.battle_log) > 30:
            self.battle_log = self.battle_log[-30:]

    # ═══════════════════════════════════════════════════════════════════════════
    #  MAIN LOOP
    # ═══════════════════════════════════════════════════════════════════════════

    def run(self):
        while self.running:
            dt = self.clock.tick(FPS)
            now = pygame.time.get_ticks()
            mouse = pygame.mouse.get_pos()
            self.ui.tick()
            events = pygame.event.get()

            for e in events:
                if e.type == pygame.QUIT:
                    self.running = False

            if self.state == STATE_LOGIN:
                self._handle_login(events, mouse)
                self._draw_login(mouse)
            elif self.state == STATE_MENU:
                self._handle_menu(events, mouse)
                self._draw_menu(mouse)
            elif self.state == STATE_SELECT:
                self._handle_select(events, mouse)
                self._draw_select(mouse)
            elif self.state == STATE_COMBAT:
                self._handle_combat(events, mouse, now)
                self._draw_combat(mouse, now)
            elif self.state == STATE_BOSS_ROUND:
                self._run_boss_round()
            elif self.state == STATE_GAMEOVER:
                self._handle_gameover(events, mouse)
                self._draw_gameover(mouse)

            pygame.display.flip()

        pygame.quit()
        _cleanup_offline()

    # ═══════════════════════════════════════════════════════════════════════════
    #  LOGIN & AUTHENTICATION SCREEN
    # ═══════════════════════════════════════════════════════════════════════════

    def _get_auth_rects(self):
        panel_w, panel_h = 500, 440
        panel_x = W // 2 - panel_w // 2
        panel_y = 180
        tab_w = panel_w // 2
        tab_login_r = pygame.Rect(panel_x, panel_y, tab_w, 44)
        tab_reg_r   = pygame.Rect(panel_x + tab_w, panel_y, tab_w, 44)
        user_r      = pygame.Rect(panel_x + 35, panel_y + 80, panel_w - 70, 44)
        pass_r      = pygame.Rect(panel_x + 35, panel_y + 160, panel_w - 135, 44)
        eye_r       = pygame.Rect(panel_x + panel_w - 90, panel_y + 160, 55, 44)
        submit_r    = pygame.Rect(panel_x + 35, panel_y + 255, panel_w - 70, 50)
        guest_r     = pygame.Rect(panel_x + 35, panel_y + 320, (panel_w - 85) // 2, 44)
        exit_r      = pygame.Rect(panel_x + 50 + (panel_w - 85) // 2, panel_y + 320, (panel_w - 85) // 2, 44)
        return {
            "panel": pygame.Rect(panel_x, panel_y, panel_w, panel_h),
            "tab_login": tab_login_r,
            "tab_reg": tab_reg_r,
            "user": user_r,
            "pass": pass_r,
            "eye": eye_r,
            "submit": submit_r,
            "guest": guest_r,
            "exit": exit_r,
        }

    def _submit_auth(self):
        uname = (self.login_username or "").strip()
        pwd = self.login_password or ""
        if not uname:
            self.login_status_msg = "Please enter your username."
            self.login_status_color = C_RED
            self.login_active_field = "username"
            return
        if not pwd:
            self.login_status_msg = "Please enter your password."
            self.login_status_color = C_RED
            self.login_active_field = "password"
            return

        if self.login_mode == "login":
            success, msg = self.auth.login(uname, pwd)
            if success:
                self.login_status_msg = msg
                self.login_status_color = C_GREEN
                self.logger.set_player(uname)
                try:
                    if get_client_sync:
                        get_client_sync().start_heartbeat_loop(uname, hero_class="Lobby")
                except Exception:
                    pass
                self.state = STATE_MENU
            else:
                self.login_status_msg = msg
                self.login_status_color = C_RED
        else:
            success, msg = self.auth.register(uname, pwd)
            if success:
                self.login_status_msg = msg
                self.login_status_color = C_GREEN
                self.logger.set_player(uname)
                try:
                    if get_client_sync:
                        get_client_sync().start_heartbeat_loop(uname, hero_class="Lobby")
                except Exception:
                    pass
                self.state = STATE_MENU
            else:
                self.login_status_msg = msg
                self.login_status_color = C_RED

    def _handle_login(self, events, mouse):
        rects = self._get_auth_rects()
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if rects["tab_login"].collidepoint(mouse):
                    self.login_mode = "login"
                    self.login_status_msg = ""
                elif rects["tab_reg"].collidepoint(mouse):
                    self.login_mode = "register"
                    self.login_status_msg = ""
                elif rects["user"].collidepoint(mouse):
                    self.login_active_field = "username"
                elif rects["pass"].collidepoint(mouse):
                    self.login_active_field = "password"
                elif rects["eye"].collidepoint(mouse):
                    self.login_show_password = not self.login_show_password
                elif rects["submit"].collidepoint(mouse):
                    self._submit_auth()
                elif rects["guest"].collidepoint(mouse):
                    guest_name = self.auth.guest_login()
                    self.logger.set_player(guest_name)
                    try:
                        if get_client_sync:
                            get_client_sync().start_heartbeat_loop(guest_name, hero_class="Lobby")
                    except Exception:
                        pass
                    self.state = STATE_MENU
                elif rects["exit"].collidepoint(mouse):
                    self.running = False
                else:
                    if not rects["panel"].collidepoint(mouse):
                        self.login_active_field = None

            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_TAB:
                    if self.login_active_field == "username":
                        self.login_active_field = "password"
                    else:
                        self.login_active_field = "username"
                elif e.key == pygame.K_RETURN:
                    self._submit_auth()
                elif e.key == pygame.K_ESCAPE:
                    if self.auth.is_logged_in():
                        self.state = STATE_MENU
                elif e.key == pygame.K_BACKSPACE:
                    if self.login_active_field == "username":
                        self.login_username = self.login_username[:-1]
                    elif self.login_active_field == "password":
                        self.login_password = self.login_password[:-1]
                else:
                    if e.unicode and len(e.unicode) == 1:
                        if self.login_active_field == "username" and len(self.login_username) < 22:
                            if e.unicode.isalnum() or e.unicode in ("_", "-"):
                                self.login_username += e.unicode
                        elif self.login_active_field == "password" and len(self.login_password) < 32:
                            if ord(e.unicode) >= 32:
                                self.login_password += e.unicode

    def _draw_login(self, mouse):
        # Background
        if self.backgrounds:
            self.screen.blit(self.backgrounds[0][1], (0, 0))
        else:
            self.screen.fill((10, 8, 20))

        # Dark overlay
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 175))
        self.screen.blit(overlay, (0, 0))
        self._update_draw_particles()

        # Title Glow & Header
        glow = glow_surface((750, 180), (120, 60, 220), alpha=65)
        self.screen.blit(glow, glow.get_rect(center=(W // 2, 105)))

        tf = self.fonts["title"]
        title_s = tf.render("ARCANE  CLASH", True, C_GOLD)
        self.screen.blit(title_s, title_s.get_rect(center=(W // 2, 90)))

        sf = self.fonts["small"]
        sub_s = sf.render("Player Authentication & Playstyle Archival", True, (185, 145, 255))
        self.screen.blit(sub_s, sub_s.get_rect(center=(W // 2, 135)))

        rects = self._get_auth_rects()
        p = rects["panel"]

        # Card Panel Background
        panel_surf = pygame.Surface((p.w, p.h), pygame.SRCALPHA)
        panel_surf.fill((18, 14, 32, 235))
        self.screen.blit(panel_surf, p.topleft)
        pygame.draw.rect(self.screen, (130, 70, 220), p, 2, border_radius=14)

        # Tabs
        login_active = (self.login_mode == "login")
        col_login_bg = (38, 28, 64) if login_active else (14, 10, 25)
        col_reg_bg   = (38, 28, 64) if not login_active else (14, 10, 25)
        pygame.draw.rect(self.screen, col_login_bg, rects["tab_login"], border_top_left_radius=14)
        pygame.draw.rect(self.screen, col_reg_bg, rects["tab_reg"], border_top_right_radius=14)
        if login_active:
            pygame.draw.line(self.screen, C_GOLD, rects["tab_login"].bottomleft, rects["tab_login"].bottomright, 3)
        else:
            pygame.draw.line(self.screen, C_GOLD, rects["tab_reg"].bottomleft, rects["tab_reg"].bottomright, 3)

        tab_f = self.fonts["small"]
        t1 = tab_f.render("▶  PLAYER LOGIN", True, C_GOLD if login_active else C_LIGHT_GRAY)
        t2 = tab_f.render("✦  REGISTER NEW HERO", True, C_GOLD if not login_active else C_LIGHT_GRAY)
        self.screen.blit(t1, t1.get_rect(center=rects["tab_login"].center))
        self.screen.blit(t2, t2.get_rect(center=rects["tab_reg"].center))

        # Username Input
        self.ui.draw_input_field(
            "auth_uname", "PLAYER USERNAME", rects["user"],
            self.login_username, (self.login_active_field == "username"),
            placeholder="Choose or enter hero name...", mouse_pos=mouse
        )

        # Password Input
        self.ui.draw_input_field(
            "auth_pwd", "SECRET PASSWORD", rects["pass"],
            self.login_password, (self.login_active_field == "password"),
            placeholder="Enter password (min 4 chars)...", mask=(not self.login_show_password), mouse_pos=mouse
        )

        # Show/Hide eye button
        eye_label = "🔒" if not self.login_show_password else "👁"
        self.ui.draw_button(
            "auth_eye", eye_label, rects["eye"],
            color=(55, 45, 80), mouse_pos=mouse
        )

        # Status message
        if self.login_status_msg:
            stat_f = self.fonts["small"]
            msg_s = stat_f.render(self.login_status_msg, True, self.login_status_color)
            self.screen.blit(msg_s, msg_s.get_rect(centerx=p.centerx, centery=p.y + 225))

        # Primary Submit Button
        btn_label = "▶  LOGIN TO REALM" if login_active else "✦  CREATE ACCOUNT & ENTER"
        btn_col   = (100, 50, 190) if login_active else (40, 130, 90)
        self.ui.draw_button("auth_submit", btn_label, rects["submit"], color=btn_col, mouse_pos=mouse)

        # Guest & Exit buttons
        self.ui.draw_button("auth_guest", "👤 Guest Access", rects["guest"], color=(45, 75, 115), mouse_pos=mouse)
        self.ui.draw_button("auth_exit", "✕ Exit Game", rects["exit"], color=(135, 35, 55), mouse_pos=mouse)

        # Footer Notice
        tiny_f = self.fonts["tiny"]
        sec_msg = tiny_f.render("🔒 PBKDF2 Encrypted Authentication • Game logs stored under your username", True, (120, 110, 145))
        self.screen.blit(sec_msg, sec_msg.get_rect(centerx=W // 2, bottom=H - 18))

    # ═══════════════════════════════════════════════════════════════════════════
    #  MENU SCREEN
    # ═══════════════════════════════════════════════════════════════════════════

    def _handle_menu(self, events, mouse):
        play_r   = pygame.Rect(W // 2 - 130, 310, 260, 50)
        dash_r   = pygame.Rect(W // 2 - 130, 370, 260, 50)
        switch_r = pygame.Rect(W // 2 - 130, 430, 260, 50)
        exit_r   = pygame.Rect(W // 2 - 130, 490, 260, 50)
        badge_r  = pygame.Rect(W - 270, 20, 250, 42)

        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if play_r.collidepoint(mouse):
                    self.state = STATE_SELECT
                elif dash_r.collidepoint(mouse):
                    open_dashboard()
                elif switch_r.collidepoint(mouse) or badge_r.collidepoint(mouse):
                    self.state = STATE_LOGIN
                    self.login_status_msg = ""
                elif exit_r.collidepoint(mouse):
                    self.running = False

    def _draw_menu(self, mouse):
        # Background
        if self.backgrounds:
            self.screen.blit(self.backgrounds[0][1], (0, 0))
        else:
            self.screen.fill((10, 8, 20))

        # Dark overlay
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        self._update_draw_particles()

        # Active User Badge (Top Right)
        cur_user = self.auth.get_username() or "Guest Player"
        badge_r = pygame.Rect(W - 270, 20, 250, 42)
        self.ui.draw_button(
            "menu_user_badge", f"👤 {cur_user}", badge_r,
            color=(45, 30, 75), mouse_pos=mouse, sub_label="Click to switch"
        )

        # Title glow
        glow = glow_surface((700, 200), (120, 60, 220), alpha=60)
        self.screen.blit(glow, glow.get_rect(center=(W // 2, 180)))

        tf = self.fonts["title"]
        title1 = tf.render("ARCANE  CLASH", True, C_GOLD)
        self.screen.blit(title1, title1.get_rect(center=(W // 2, 160)))

        sf = self.fonts["small"]
        sub = sf.render("A Turn-Based Wizard RPG", True, (180, 140, 255))
        self.screen.blit(sub, sub.get_rect(center=(W // 2, 210)))

        # Sub-badge indicating player log directory
        tiny_f = self.fonts["tiny"]
        log_dest_str = f"Archiving combat logs to: /logs/{cur_user}/"
        log_dest_surf = tiny_f.render(log_dest_str, True, (120, 200, 150))
        self.screen.blit(log_dest_surf, log_dest_surf.get_rect(center=(W // 2, 245)))

        self.ui.draw_button("menu_play", "▶  Play Game", pygame.Rect(W // 2 - 130, 310, 260, 50),
                             color=(90, 50, 180), mouse_pos=mouse)
        self.ui.draw_button("menu_dash", "📊 Live Dashboard", pygame.Rect(W // 2 - 130, 370, 260, 50),
                             color=(30, 120, 210), mouse_pos=mouse)
        self.ui.draw_button("menu_switch", "👤 Switch Player / Login", pygame.Rect(W // 2 - 130, 430, 260, 50),
                             color=(60, 40, 100), mouse_pos=mouse)
        self.ui.draw_button("menu_exit", "✕  Exit Game", pygame.Rect(W // 2 - 130, 490, 260, 50),
                             color=(140, 30, 50), mouse_pos=mouse)

        # Version tag
        vt = self.fonts["tiny"].render("v2.0 — User Authenticated Edition", True, (90, 80, 125))
        self.screen.blit(vt, (10, H - 20))

    # ═══════════════════════════════════════════════════════════════════════════
    #  SELECTION SCREEN
    # ═══════════════════════════════════════════════════════════════════════════

    def _handle_select(self, events, mouse):
        hero_rects = self._hero_card_rects()
        bg_rects   = self._bg_card_rects()
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                for i, r in enumerate(hero_rects):
                    if r.collidepoint(mouse):
                        self.selected_hero_idx = i
                for i, r in enumerate(bg_rects):
                    if r.collidepoint(mouse):
                        self.selected_bg_idx = i
                start_r = pygame.Rect(W // 2 - 130, H - 80, 260, 55)
                back_r  = pygame.Rect(30, H - 70, 140, 45)
                if start_r.collidepoint(mouse):
                    self.start_combat()
                elif back_r.collidepoint(mouse):
                    self.state = STATE_MENU

    def _hero_card_rects(self):
        cw, ch = 200, 260
        total = len(HEROES)
        start_x = W // 2 - (total * cw + (total - 1) * 20) // 2
        return [pygame.Rect(start_x + i * (cw + 20), 130, cw, ch)
                for i in range(total)]

    def _bg_card_rects(self):
        cw, ch = 160, 100
        n = min(len(self.backgrounds), 5)
        start_x = W // 2 - (n * cw + (n - 1) * 12) // 2
        return [pygame.Rect(start_x + i * (cw + 12), 440, cw, ch)
                for i in range(n)]

    def _draw_select(self, mouse):
        if self.backgrounds:
            self.screen.blit(self.backgrounds[self.selected_bg_idx][1], (0, 0))
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))
        self._update_draw_particles()

        # Title
        tf = self.fonts["title"]
        t = tf.render("Choose Your Hero & Arena", True, C_GOLD)
        self.screen.blit(t, t.get_rect(center=(W // 2, 70)))

        sf = self.fonts["small"]
        ht = sf.render("━━  Heroes  ━━", True, (180, 140, 255))
        self.screen.blit(ht, ht.get_rect(center=(W // 2, 110)))

        # Hero cards
        hero_rects = self._hero_card_rects()
        for i, (r, hd) in enumerate(zip(hero_rects, HEROES)):
            sel = (i == self.selected_hero_idx)
            thumb = self.hero_thumbs[i] if i < len(self.hero_thumbs) else None
            self.ui.draw_selection_card(f"hero_{i}", hd["name"], r,
                                         thumbnail=thumb, selected=sel, mouse_pos=mouse)
            # Description
            for j, line in enumerate(hd["desc"].split("\n")):
                dt = self.fonts["tiny"].render(line, True, (160, 150, 190))
                self.screen.blit(dt, dt.get_rect(centerx=r.centerx, y=r.bottom + 6 + j * 14))

        bt = sf.render("━━  Arena / Background  ━━", True, (180, 140, 255))
        self.screen.blit(bt, bt.get_rect(center=(W // 2, 420)))

        # Background cards
        bg_rects = self._bg_card_rects()
        for i, r in enumerate(bg_rects):
            if i >= len(self.backgrounds):
                break
            sel = (i == self.selected_bg_idx)
            thumb = self.bg_thumbs[i] if i < len(self.bg_thumbs) else None
            self.ui.draw_selection_card(f"bg_{i}", self.backgrounds[i][0], r,
                                         thumbnail=thumb, selected=sel, mouse_pos=mouse)

        # Buttons
        self.ui.draw_button("sel_start", "⚔  Begin Battle", pygame.Rect(W // 2 - 130, H - 80, 260, 55),
                             color=(90, 50, 180), mouse_pos=mouse)
        self.ui.draw_button("sel_back", "← Back", pygame.Rect(30, H - 70, 140, 45),
                             color=(60, 55, 90), mouse_pos=mouse)

    # ═══════════════════════════════════════════════════════════════════════════
    #  COMBAT SCREEN — EVENT HANDLING
    # ═══════════════════════════════════════════════════════════════════════════

    def _handle_combat(self, events, mouse, now):
        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if self.phase == PHASE_HERO_TURN:
                    panel_rect = pygame.Rect(0, H - 195, 500, 195)
                    btn_rects = self.ui.draw_attack_panel(
                        self.hero, mouse, panel_rect) or {}
                    for key, rect in btn_rects.items():
                        if rect.collidepoint(mouse) and self.hero.can_use(key):
                            self._hero_attack(key, now)
                            break

            if e.type == pygame.MOUSEMOTION:
                if self.phase == PHASE_HERO_TURN:
                    panel_rect = pygame.Rect(0, H - 195, 500, 195)
                    btn_rects = self.ui.draw_attack_panel(
                        self.hero, mouse, panel_rect) or {}
                    self.hovered_attack = None
                    for key, rect in btn_rects.items():
                        if rect.collidepoint(mouse):
                            self.hovered_attack = key
                            break

        # ── Gameover timer — MUST be the first check; returns early so no
        #    combat phase ever runs again once death is triggered. ────────────
        if self._gameover_at > 0:
            if now >= self._gameover_at:
                self._gameover_at = 0
                self.state = STATE_GAMEOVER
            return   # skip ALL phase logic while dying

        # ── Phase transitions based on animation-done flags ─────────────────
        # Flags are SET inside _draw_combat when update() returns True.
        # They are CLEARED here after the transition fires.

        if self.phase == PHASE_HERO_ANIM:
            # Timed actions (rest/heal) finish via countdown, not animation-done
            timed_done = (self._timed_action_at > 0 and now >= self._timed_action_at)
            if timed_done:
                self._timed_action_at = 0
                self._hero_anim_finished = True

            if self._hero_anim_finished:
                self._hero_anim_finished = False
                # Spawn spell effect travelling toward villain
                eff_key = ATTACK_EFFECT_MAP.get(self.pending_hero_attack)
                villain_center = (self.villain_pos[0], self.villain_pos[1] - 130)
                if eff_key:
                    self.spawn_effect(eff_key, villain_center, scale=0.18)
                self.phase = PHASE_EFFECT

        if self.phase == PHASE_EFFECT:
            all_done = not self.active_effects or all(e.finished for e in self.active_effects)
            if all_done:
                self.active_effects.clear()
                r = self._last_hero_result
                villain_top = (self.villain_pos[0], self.villain_pos[1] - 160)
                if r["hit"]:
                    self.villain_sprite.play("hurt", loop=False, then="idle")
                    if r["dmg"] > 0:
                        self.spawn_float(f"-{r['dmg']}", villain_top, color=(255, 80, 80))
                    if r["effect_msg"]:
                        self.spawn_float(r["effect_msg"],
                                          (self.villain_pos[0], self.villain_pos[1] - 200),
                                          color=(255, 220, 50))
                else:
                    self.spawn_float("MISS!", villain_top, color=(200, 200, 200))

                # Check villain dead
                if self.villain.state == "dead":
                    self.villain_sprite.play("dead", loop=False)
                    self._end_game(won=True)
                    return

                # Wait then villain acts
                self.phase = PHASE_VILLAIN_TURN
                self._villain_turn_at = now + 900

        # Villain-turn delay (simple timestamp, no pygame timer events)
        if self.phase == PHASE_VILLAIN_TURN:
            if now >= getattr(self, "_villain_turn_at", 0):
                self._villain_attack(now)

        if self.phase == PHASE_VILLAIN_ANIM:
            if self._villain_anim_finished:
                self._villain_anim_finished = False
                eff_key = ATTACK_EFFECT_MAP.get(self.pending_villain_attack)
                hero_center = (self.hero_pos[0], self.hero_pos[1] - 130)
                if eff_key:
                    self.spawn_effect(eff_key, hero_center, scale=0.15)
                self.phase = PHASE_RESULT

        if self.phase == PHASE_RESULT:
            all_done = not self.active_effects or all(e.finished for e in self.active_effects)
            if all_done:
                self.active_effects.clear()
                r = self._last_villain_result
                hero_top = (self.hero_pos[0], self.hero_pos[1] - 160)
                if r["hit"]:
                    self.hero_sprite.play("hurt", loop=False, then="idle")
                    if r["dmg"] > 0:
                        self.spawn_float(f"-{r['dmg']}", hero_top, color=(255, 80, 80))
                    if r["effect_msg"]:
                        self.spawn_float(r["effect_msg"],
                                          (self.hero_pos[0], self.hero_pos[1] - 200),
                                          color=(255, 220, 50))
                else:
                    self.spawn_float("MISS!", hero_top, color=(200, 200, 200))

                if self.hero.state == "dead":
                    self.hero_sprite.play("dead", loop=False)
                    self._end_game(won=False)
                    return

                # Record villain resolution in logger for this round
                dmg_taken = r["dmg"] if r["hit"] else 0
                boss_act = r.get("attack_key") or self.pending_villain_attack or self.boss_actual_act
                if hasattr(self.logger, "log_boss_turn_resolution"):
                    self.logger.log_boss_turn_resolution(dmg_taken, self.hero.hp, boss_act)
                elif hasattr(self.logger, "log_boss_response"):
                    self.logger.log_boss_response(boss_act, dmg_taken, self.hero.hp)

                # Check for boss phase transition (e.g., if DoT triggered threshold)
                self._check_boss_phase_transition()

                # Advance to next hero turn & generate next boss telegraph
                self.phase = PHASE_HERO_TURN
                self.hovered_attack = None
                self.turn_number += 1
                if self.boss_phase == 2:
                    self.phase2_boss_turns_count += 1

                self.boss_telegraphed_act, self.boss_actual_act, self.boss_is_feint, self.latest_adaptive_weights = (
                    self.villain.plan_next_attack(adaptive_memory=self.adaptive_memory)
                )

                # Phase 2 feature: every 3rd boss turn skips telegraphing entirely (player sees "???")
                if self.boss_phase == 2 and (self.phase2_boss_turns_count % 3 == 0):
                    self.boss_telegraphed_act = "???"
                    self.log(f"Turn {self.turn_number}: {self.villain.name} masks its intent! Preparing: ???")
                else:
                    telegraphed_label = Entity.ATTACKS[self.boss_telegraphed_act]["label"]
                    self.log(f"Turn {self.turn_number}: {self.villain.name} prepares {telegraphed_label}!")

                self.hero_turn_started_at = pygame.time.get_ticks()
                self.logger.mark_turn_start()

    # ─── BOSS PHASE SHIFTS ───────────────────────────────────────────────────

    def _check_boss_phase_transition(self):
        """Check if boss crossed an HP threshold and trigger one-time phase transition."""
        if not self.villain or self.villain.max_hp <= 0:
            return False
        hp_ratio = self.villain.hp / self.villain.max_hp

        if hp_ratio <= 0.32 and self.boss_phase < 3:
            self.boss_phase = 3
            self.villain.boss_phase = 3
            self.villain_sprite.play("taunt", loop=False, then="idle")
            self.spawn_float("PHASE 3: DESPERATION!", (self.villain_pos[0], self.villain_pos[1] - 220), color=(255, 100, 100))
            self.log("⚠️ PHASE 3 TRANSITION: The Minotaur is FALTERING & DESPERATE! Feint rate 40%, Boss Dmg -15%!")
            return True

        elif hp_ratio <= 0.65 and self.boss_phase < 2:
            self.boss_phase = 2
            self.villain.boss_phase = 2
            self.villain_sprite.play("taunt", loop=False, then="idle")
            self.spawn_float("PHASE 2: ENRAGED!", (self.villain_pos[0], self.villain_pos[1] - 220), color=(255, 140, 40))
            self.log("🔥 PHASE 2 TRANSITION: The Minotaur ENRAGES! Unlocked ENRAGE slam, Telegraphs may be masked!")
            return True

        return False

    # ─── COMBO CHAINS EVALUATION ─────────────────────────────────────────────

    def _detect_combo(self, chosen_action):
        """
        Evaluate player's previous actions to detect combo triggers.
        Returns: (combo_name, chain_length)
        """
        last_action = self.player_action_history[-1] if self.player_action_history else None

        # Calculate active chain length leading up to this decision
        chain_len = 0
        if last_action:
            if last_action.get("action") == "water_arrow" and last_action.get("hit"):
                chain_len = 1
            elif last_action.get("action") == "rest":
                chain_len = 1
        if self.quick_slash_streak > 0:
            chain_len = max(chain_len, self.quick_slash_streak)

        # 1. Water Arrow (hit) -> Fireball
        if chosen_action == "fireball" and last_action and last_action.get("action") == "water_arrow" and last_action.get("hit"):
            return "Soaked Ignition", chain_len

        # 2. Quick Slash x3 -> 4th consecutive Quick Slash
        if chosen_action == "quick_slash" and self.quick_slash_streak >= 3:
            return "Flurry Finisher", chain_len

        # 3. Rest & Recharge -> Fire Spell
        if chosen_action == "fire_spell" and last_action and last_action.get("action") == "rest":
            return "Channelled Inferno", chain_len

        return None, chain_len

    # ─── COUNTER PLAY EVALUATION ─────────────────────────────────────────────

    def _evaluate_counter_play(self, hero_attack_key, boss_telegraph_key):
        """
        Determine if the hero's action meaningfully responded to the boss's telegraphed action.
        Returns: (is_counter, counter_type)
        """
        if not boss_telegraph_key:
            return False, None

        heavy_attacks = {"fireball", "fire_spell", "water_spell"}
        all_attacks = {"quick_slash", "fireball", "water_arrow", "water_spell", "fire_spell"}

        # 1. Boss telegraphs heavy attack -> Hero Shields (Rest) or Weakens (Water Arrow)
        if boss_telegraph_key in heavy_attacks:
            if hero_attack_key == "rest":
                return True, "shield_vs_heavy"
            if hero_attack_key == "water_arrow":
                return True, "weaken_vs_heavy"

        # 2. Boss telegraphs standard attack -> Hero Weakens or Shields
        if boss_telegraph_key in all_attacks:
            if hero_attack_key == "water_arrow":
                return True, "weaken_vs_attack"
            if hero_attack_key == "rest":
                return True, "shield_vs_attack"

        # 3. Boss telegraphs Rest -> Hero punishes with an attack
        if boss_telegraph_key == "rest":
            if hero_attack_key in all_attacks:
                return True, "punish_rest"

        # 4. Critical HP (< 30) -> Defensive survival (Heal or Rest)
        if self.hero and self.hero.hp < 30 and hero_attack_key in ("heal", "rest"):
            return True, "emergency_defense"

        return False, None

    # ─── HERO ATTACK ─────────────────────────────────────────────────────────

    def _hero_attack(self, attack_key, now):
        self.pending_hero_attack = attack_key

        # Capture state before action for ML logging
        player_hp_before = self.hero.hp
        player_xp_before = self.hero.xp
        player_power_before = self.hero.power
        boss_hp_before = self.villain.hp

        status_effects = []
        if self.hero.is_burning:
            status_effects.append("Burning")
        if self.hero.is_exhausted:
            status_effects.append("Exhausted")
        if self.hero.is_weakened:
            status_effects.append("Weakened")
        if self.hero.is_defending or self.hero.is_counter_shielded:
            status_effects.append("Shielded")

        cooldowns_snapshot = dict(self.hero.cooldowns)
        time_taken_ms = max(0, int(now - getattr(self, "hero_turn_started_at", now)))

        # Evaluate combo triggers
        combo_name, chain_len = self._detect_combo(attack_key)

        # Evaluate counter play
        is_counter, counter_type = self._evaluate_counter_play(attack_key, self.boss_telegraphed_act)

        # Trigger soft counters
        if is_counter:
            if counter_type in ("weaken_vs_heavy", "weaken_vs_attack"):
                self.villain.is_counter_weakened = True
                self.spawn_float("COUNTER WEAKEN!", (self.villain_pos[0], self.villain_pos[1] - 200),
                                 color=(255, 230, 80))
                self.log("Soft Counter: Water Arrow weakened the boss's incoming strike (-65% dmg)!")
            elif counter_type == "shield_vs_heavy":
                self.hero.is_counter_shielded = True
                self.spawn_float("PERFECT GUARD READY!", (self.hero_pos[0], self.hero_pos[1] - 200),
                                 color=(100, 240, 255))
                self.log("Soft Counter: Perfect Guard prepared against heavy attack (60% absorption)!")

        # Execute hero attack with combo bonuses
        result = self.hero.perform_attack(attack_key, self.villain, combo=combo_name)
        self._last_hero_result = result

        # Display combo visual indicator & log
        if combo_name:
            self.spawn_float(f"COMBO: {combo_name}!", (self.hero_pos[0], self.hero_pos[1] - 220), color=(255, 215, 0))
            self.log(f"💥 COMBO TRIGGERED: {combo_name}!")

        # Update combo streak state & action memory
        if attack_key == "quick_slash":
            if combo_name == "Flurry Finisher":
                self.quick_slash_streak = 0
            else:
                self.quick_slash_streak += 1
        else:
            self.quick_slash_streak = 0

        self.player_action_history.append({
            "action": attack_key,
            "hit": result.get("hit", False),
            "turn": self.turn_number,
        })
        self.adaptive_memory.record_player_action(attack_key)

        # Check for boss phase transitions caused by damage
        phase_transition_occurred = self._check_boss_phase_transition()
        self.last_phase_transition_occurred = phase_transition_occurred

        # Log player action to BattleLogger
        atk_label = Entity.ATTACKS[attack_key]["label"]
        if self.boss_telegraphed_act == "???":
            telegraphed_label = "???"
        elif self.boss_telegraphed_act:
            telegraphed_label = Entity.ATTACKS[self.boss_telegraphed_act]["label"]
        else:
            telegraphed_label = "None"

        self.logger.log_player_action(
            turn_number=self.turn_number,
            action_chosen=atk_label,
            boss_telegraphed_action=telegraphed_label,
            action_matched_counter=is_counter,
            player_hp_before=player_hp_before,
            boss_hp_before=boss_hp_before,
            player_xp_before=player_xp_before,
            player_power_before=player_power_before,
            status_effects_active=status_effects,
            cooldowns_active=cooldowns_snapshot,
            hit_success=result.get("hit", False),
            damage_dealt=result.get("dmg", 0),
            player_hp_after=self.hero.hp,
            boss_hp_after=self.villain.hp,
            player_xp_after=self.hero.xp,
            player_power_after=self.hero.power,
            time_taken_ms=time_taken_ms,
            combo_triggered=combo_name,
            combo_chain_length_at_decision=chain_len,
            boss_phase_at_decision=self.boss_phase,
            phase_transition_occurred=phase_transition_occurred,
            boss_adaptive_weights_snapshot=self.latest_adaptive_weights,
        )

        anim = ATTACK_ANIM_MAP.get(attack_key, "attack1")
        self.phase = PHASE_HERO_ANIM
        self.active_effects.clear()

        if attack_key in TIMED_ACTIONS:
            # Rest / Heal: play idle loop + wait fixed time, no animation-done needed
            self.hero_sprite.play("idle", loop=True)
            self._timed_action_at = now + 900
        else:
            self.hero_sprite.play(anim, loop=False, then="idle")
            self._timed_action_at = 0

        atk_info = Entity.ATTACKS[attack_key]
        if attack_key == "rest":
            self.log(f"You rest and recharge!  {result['effect_msg']}")
        elif result["hit"]:
            self.log(f"You: {atk_info['label']}!  Dealt {result['dmg']} dmg.")
            if result["effect_msg"]:
                self.log(f"  {result['effect_msg']}")
        else:
            self.log(f"You: {atk_info['label']} MISSED!")

    # ─── VILLAIN ATTACK ───────────────────────────────────────────────────────

    def _villain_attack(self, now):
        # Apply DoT / burn damage at villain's turn start
        msgs = self.villain.apply_turn_effects()
        for m in msgs:
            self.log(m)
            self.spawn_float(m, (self.villain_pos[0], self.villain_pos[1] - 160),
                              color=(255, 120, 40))

        if self.villain.state == "dead":
            self.villain_sprite.play("dead", loop=False)
            self._end_game(won=True)
            return

        if not self.boss_actual_act:
            atk_key, _ = self.villain.choose_enemy_attack(adaptive_memory=self.adaptive_memory)
        else:
            atk_key = self.boss_actual_act
        self.pending_villain_attack = atk_key

        if self.boss_is_feint and self.boss_telegraphed_act != atk_key:
            if self.boss_telegraphed_act in Entity.ATTACKS:
                telegraphed_lbl = Entity.ATTACKS[self.boss_telegraphed_act]["label"]
            else:
                telegraphed_lbl = str(self.boss_telegraphed_act)
            actual_lbl = Entity.ATTACKS.get(atk_key, {}).get("label", str(atk_key))
            self.log(f"⚡ FEINT! {self.villain.name} feinted {telegraphed_lbl} and switched to {actual_lbl}!")
            self.spawn_float("FEINT!", (self.villain_pos[0], self.villain_pos[1] - 180), color=(255, 120, 220))

        result = self.villain.perform_attack(atk_key, self.hero)
        self._last_villain_result = result
        self.active_effects.clear()

        atk_info = Entity.ATTACKS[atk_key]
        if atk_key == "rest":
            # Villain rests: no attack animation, just idle + short delay
            self.villain_sprite.play("idle", loop=True)
            self.log(f"Enemy rests!  {result['effect_msg']}")
            self.spawn_float("Enemy RESTS",
                              (self.villain_pos[0], self.villain_pos[1] - 160),
                              color=(150, 200, 255))
            # Skip straight to RESULT phase after short pause
            self.phase = PHASE_RESULT
            # Force an empty result so nothing bad is applied to hero
            self._last_villain_result = {"hit": False, "dmg": 0,
                                          "effect_msg": "", "attack_key": "rest"}
        else:
            self.villain_sprite.play("attack1", loop=False, then="idle")
            self.phase = PHASE_VILLAIN_ANIM
            if result["hit"]:
                self.log(f"Enemy: {atk_info['label']}!  Dealt {result['dmg']} dmg.")
                if result["effect_msg"]:
                    self.log(f"  {result['effect_msg']}")
            else:
                self.log(f"Enemy: {atk_info['label']} MISSED!")

        # Apply hero DoT / passive regen (burn ticks etc.)
        hero_msgs = self.hero.apply_turn_effects()
        for m in hero_msgs:
            self.log(m)

    # ─── END GAME ────────────────────────────────────────────────────────────

    def _end_game(self, won):
        self.won = won
        self.phase = PHASE_RESULT          # keep drawing last frame
        self.logger.end_match(won, self.hero.hp if self.hero else 0)
        # Ensure server is running and auto-open dashboard upon match completion
        try:
            ensure_server_running()
            if not getattr(self, "_dashboard_opened_for_match", False):
                self._dashboard_opened_for_match = True
                open_dashboard()
        except Exception as e:
            print(f"[Game] Dashboard auto-open notice: {e}")

        # If player won round 1, queue the Boss Round instead of going directly to gameover
        if won and not getattr(self, "_boss_round_triggered", False) and launch_boss_round is not None:
            self._boss_round_triggered = True
            # Small delay then enter boss round state (skip normal gameover timer)
            self._gameover_at = 0            # no auto-gameover
            self.state = STATE_BOSS_ROUND    # handled in run loop
        else:
            self._gameover_at = pygame.time.get_ticks() + 1800

    def _run_boss_round(self):
        """Run the post-round-1 Boss Round gauntlet."""
        if launch_boss_round is None:
            self.state = STATE_GAMEOVER
            return

        boss_won = launch_boss_round(
            screen=self.screen,
            clock=self.clock,
            fonts=self.fonts,
            backgrounds=self.backgrounds,
            hero=self.hero,
            hero_sprite=self.hero_sprite,
            effects_lib=getattr(self, "effects_lib", getattr(self, "effects", {})),
            predicted_style=getattr(self, "agent_predicted_playstyle", None)
            or getattr(self.logger, "predicted_playstyle", None)
            or getattr(self, "predicted_playstyle", None),
        )
        self.won = boss_won
        self.phase = PHASE_RESULT
        self._gameover_at = 0
        self.state = STATE_GAMEOVER

    # ═══════════════════════════════════════════════════════════════════════════
    #  COMBAT SCREEN — DRAWING
    # ═══════════════════════════════════════════════════════════════════════════

    def _draw_combat(self, mouse, now):
        # Background
        bg = self.backgrounds[self.selected_bg_idx][1]
        self.screen.blit(bg, (0, 0))

        # Subtle dark vignette at bottom
        vignette = pygame.Surface((W, 220), pygame.SRCALPHA)
        for i in range(220):
            alpha = int(i * 0.9)
            pygame.draw.rect(vignette, (5, 3, 15, alpha), (0, i, W, 1))
        self.screen.blit(vignette, (0, H - 220))

        # ── Animate sprites — update() returns True when one-shot finishes ──
        if self.hero_sprite.update(now):
            self._hero_anim_finished = True
        if self.villain_sprite.update(now):
            self._villain_anim_finished = True

        # Shadow under characters (at their feet = midbottom position)
        for pos in [self.hero_pos, self.villain_pos]:
            shadow = pygame.Surface((200, 24), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow, (0, 0, 0, 90), (0, 0, 200, 24))
            self.screen.blit(shadow, (pos[0] - 100, pos[1] - 12))

        # Draw villain (right side) — midbottom at villain_pos
        vs = self.villain_sprite.get_surface()
        if vs:
            vr = vs.get_rect(midbottom=self.villain_pos)
            self.screen.blit(vs, vr)

        # Draw hero (left side) — midbottom at hero_pos
        hs = self.hero_sprite.get_surface()
        if hs:
            hr = hs.get_rect(midbottom=self.hero_pos)
            self.screen.blit(hs, hr)

        # ── Spell effects ──────────────────────────────────────────────────
        for eff in self.active_effects[:]:
            eff.update(now)
            eff.draw(self.screen)
        self.active_effects = [e for e in self.active_effects if not e.finished]

        # ── HUDs ───────────────────────────────────────────────────────────
        hero_panel = pygame.Rect(10, 10, 280, 110)
        self.ui.draw_hero_hud(self.hero, hero_panel)

        villain_panel = pygame.Rect(W - 290, 10, 280, 70)
        self.ui.draw_villain_hud(self.villain, villain_panel)

        # ── Boss intent banner (telegraphed during player's turn) ───────────
        if self.phase == PHASE_HERO_TURN and self.boss_telegraphed_act:
            intent_rect = pygame.Rect(W - 290, 86, 280, 44)
            self.ui.draw_boss_intent(self.boss_telegraphed_act, intent_rect)

        # ── Turn banner ────────────────────────────────────────────────────
        if self.phase == PHASE_HERO_TURN:
            self.ui.draw_turn_banner("YOUR TURN", C_GREEN)
        elif self.phase in (PHASE_VILLAIN_TURN, PHASE_VILLAIN_ANIM):
            self.ui.draw_turn_banner("ENEMY TURN", C_RED)
        elif self.phase == PHASE_HERO_ANIM:
            self.ui.draw_turn_banner("Attacking...", (200, 160, 255))
        elif self.phase == PHASE_EFFECT:
            self.ui.draw_turn_banner("Spell in flight!", (255, 160, 60))

        # ── Attack panel (only on hero's turn) ────────────────────────────
        if self.phase == PHASE_HERO_TURN:
            panel_rect = pygame.Rect(0, H - 195, 500, 195)
            self.ui.draw_attack_panel(self.hero, mouse, panel_rect)
            if self.hovered_attack:
                self.ui.draw_tooltip(self.hovered_attack, mouse, hero=self.hero)

        # ── Battle log ─────────────────────────────────────────────────────
        log_rect = pygame.Rect(510, H - 140, W - 520, 130)
        self.ui.draw_battle_log(self.battle_log, log_rect)

        # ── Floating damage ────────────────────────────────────────────────
        self.ui.draw_floating_texts(self.float_texts, self.screen)

        # Game-over transition is handled in _handle_combat via timestamp

    # ═══════════════════════════════════════════════════════════════════════════
    #  GAME OVER SCREEN
    # ═══════════════════════════════════════════════════════════════════════════

    def _handle_gameover(self, events, mouse):
        rects = getattr(self.ui, "endscreen_button_rects", None)
        if rects:
            retry_r, dash_r, menu_r = rects
        else:
            btn_y = 125 + 440 + 15
            btn_w, btn_h = 220, 48
            gap = 20
            total_w = btn_w * 3 + gap * 2
            start_x = W // 2 - total_w // 2
            retry_r = pygame.Rect(start_x, btn_y, btn_w, btn_h)
            dash_r  = pygame.Rect(start_x + btn_w + gap, btn_y, btn_w, btn_h)
            menu_r  = pygame.Rect(start_x + (btn_w + gap) * 2, btn_y, btn_w, btn_h)

        for e in events:
            if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if retry_r.collidepoint(mouse):
                    self.start_combat()
                elif dash_r.collidepoint(mouse):
                    open_dashboard()
                elif menu_r.collidepoint(mouse):
                    self.state = STATE_MENU

    def _draw_gameover(self, mouse):
        # Show last combat frame
        bg = self.backgrounds[self.selected_bg_idx][1]
        self.screen.blit(bg, (0, 0))
        pred = getattr(self.logger, "last_prediction", None)
        agent = getattr(self.logger, "last_agent_analysis", None)
        self.ui.draw_endscreen(self.won, mouse, prediction=pred, agent_analysis=agent)


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    try:
        game = Game()
        game.run()
    except Exception as e:
        crash_file = os.path.join(BASE, "crashlog.txt")
        with open(crash_file, "w", encoding="utf-8") as f:
            f.write("=== CRASH LOG ===\n")
            f.write(str(e) + "\n")
            f.write(traceback.format_exc())
        print(f"Crashed! See {crash_file}")
        traceback.print_exc()
        pygame.quit()
        sys.exit(1)

if __name__ == "__main__":
    main()
