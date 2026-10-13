"""
db.py — Unified Database Layer (MongoDB with Resilient Local Cache Fallback).

Handles persistence of player metadata, match logs, heartbeats, and federated learning rounds.
Connects to MongoDB using MONGODB_URI from .env. If MongoDB is unreachable, it
transparently falls back to a resilient local JSON file cache (backend_storage.json),
guaranteeing that the backend and game never crash regardless of external database state.
"""

import os
import sys
import json
import time
from datetime import datetime
from dotenv import load_dotenv
from backend.auth import (
    validate_username,
    validate_password,
    hash_password,
    verify_password,
    sanitize_user_dict,
)

def get_project_root() -> str:
    cur = os.path.dirname(os.path.abspath(__file__))
    while cur and os.path.dirname(cur) != cur:
        if os.path.exists(os.path.join(cur, "Assets")) or os.path.exists(os.path.join(cur, ".env")):
            return cur
        cur = os.path.dirname(cur)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

_ROOT_DIR = get_project_root()
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

load_dotenv(os.path.join(_ROOT_DIR, ".env"))

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/arcane_clash")
DB_NAME = os.getenv("MONGODB_DB_NAME", "arcane_clash")

def _resolve_storage_file():
    p1 = os.path.join(_ROOT_DIR, "backend", "backend_storage.json")
    if os.path.exists(p1):
        return p1
    p2 = os.path.join(_ROOT_DIR, "backend_storage.json")
    if os.path.exists(p2):
        return p2
    return p1

LOCAL_FILE = _resolve_storage_file()

class Database:
    def __init__(self):
        self.use_mongo = False
        self.client = None
        self.db = None
        self.local_data = {
            "matches": [],
            "players": {},
            "users": {},
            "heartbeats": {},
            "fl_rounds": []
        }
        self._stats_cache = None
        self._stats_cache_time = 0
        self._init_connection()

    def _init_connection(self):
        # Guard against unconfigured or placeholder credentials without attempting invalid connections
        placeholder_tokens = ("<DB_USERNAME>", "<DB_PASSWORD>", "<user>", "<password>")
        if not MONGODB_URI or any(token in MONGODB_URI for token in placeholder_tokens):
            self.use_mongo = False
            print(f"[Database] Notice: MongoDB URI contains unconfigured placeholders (<DB_USERNAME>/<DB_PASSWORD>). Please supply valid MongoDB credentials in root .env to enable Atlas cloud sync. Using resilient Local Storage fallback at {LOCAL_FILE}")
            self._load_local()
            return

        try:
            from pymongo import MongoClient
            # 2.0s timeout for cloud Atlas DNS SRV resolution and TLS handshake so local fallback is fast
            client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=2000)
            client.admin.command('ping')
            self.client = client
            self.db = client[DB_NAME]
            self.use_mongo = True
            safe_target = MONGODB_URI.split('@')[-1].split('?')[0] if '@' in MONGODB_URI else 'MongoDB'
            print(f"[Database] Successfully connected to MongoDB Atlas at {safe_target}")
            # Ensure unique index on username
            try:
                self.db.users.create_index("username", unique=True)
            except Exception:
                pass
        except Exception as e:
            self.use_mongo = False
            import re
            err_msg = re.sub(r'://([^:]+):([^@]+)@', r'://\1:***@', str(e))
            print(f"[Database] MongoDB unavailable ({err_msg}). Using resilient Local Storage fallback at {LOCAL_FILE}")
            self._load_local()

    def _load_local(self):
        if os.path.exists(LOCAL_FILE):
            try:
                with open(LOCAL_FILE, "r", encoding="utf-8") as f:
                    self.local_data = json.load(f)
                    self.local_data.setdefault("users", {})
            except Exception:
                pass

    def _save_local(self):
        try:
            with open(LOCAL_FILE, "w", encoding="utf-8") as f:
                json.dump(self.local_data, f, indent=2)
        except Exception as e:
            print(f"[Database] Local save error: {e}")

    # ── User Authentication & Account Management ──────────────────────────────

    def register_user(self, username: str, password: str) -> tuple:
        """Register a new user with secure password hash & unique salt."""
        valid_u, u_res = validate_username(username)
        if not valid_u:
            return False, u_res, {}

        valid_p, p_res = validate_password(password)
        if not valid_p:
            return False, p_res, {}

        clean_user = u_res
        now = time.time()
        pwd_hash, salt = hash_password(password)

        user_doc = {
            "username": clean_user,
            "password_hash": pwd_hash,
            "salt": salt,
            "created_at": now,
            "last_login": now,
            "role": "player"
        }

        if self.use_mongo:
            try:
                existing = self.db.users.find_one({"username": clean_user})
                if existing:
                    return False, f"Username '{clean_user}' already exists.", {}
                self.db.users.insert_one(user_doc)
                self.record_player(clean_user, hero_class="Unknown", metadata={"registered": True})
                return True, f"Welcome to Arcane Clash, {clean_user}!", sanitize_user_dict(user_doc)
            except Exception as e:
                print(f"[Database] Mongo user registration note: {e}")

        # Local storage fallback
        users = self.local_data.setdefault("users", {})
        if clean_user in users:
            return False, f"Username '{clean_user}' already exists.", {}

        users[clean_user] = user_doc
        self.record_player(clean_user, hero_class="Unknown", metadata={"registered": True})
        self._save_local()
        return True, f"Welcome to Arcane Clash, {clean_user}!", sanitize_user_dict(user_doc)

    def authenticate_user(self, username: str, password: str) -> tuple:
        """Verify user credentials against stored salt and PBKDF2 hash."""
        valid_u, clean_user = validate_username(username)
        if not valid_u:
            return False, clean_user, {}

        user = None
        if self.use_mongo:
            try:
                user = self.db.users.find_one({"username": clean_user})
            except Exception as e:
                print(f"[Database] Mongo auth query note: {e}")

        if not user:
            user = self.local_data.setdefault("users", {}).get(clean_user)

        if not user:
            return False, f"User '{clean_user}' not found. Please register an account.", {}

        salt = user.get("salt")
        pwd_hash = user.get("password_hash")
        if not salt or not pwd_hash or not verify_password(password, salt, pwd_hash):
            return False, "Incorrect password. Please verify and try again.", {}

        now = time.time()
        if self.use_mongo:
            try:
                self.db.users.update_one({"username": clean_user}, {"$set": {"last_login": now}})
            except Exception:
                pass
        if clean_user in self.local_data.get("users", {}):
            self.local_data["users"][clean_user]["last_login"] = now
            self._save_local()

        self.record_player(clean_user, metadata={"last_login": now})
        return True, f"Welcome back, {clean_user}!", sanitize_user_dict(user)

    def get_user(self, username: str) -> dict:
        """Retrieve sanitized user details."""
        valid_u, clean_user = validate_username(username)
        if not valid_u:
            clean_user = username

        user = None
        if self.use_mongo:
            try:
                user = self.db.users.find_one({"username": clean_user})
            except Exception:
                pass
        if not user:
            user = self.local_data.get("users", {}).get(clean_user)
        return sanitize_user_dict(user) if user else {}

    def get_all_users(self) -> list:
        """List all registered users (stripped of sensitive hashes)."""
        res = []
        if self.use_mongo:
            try:
                cursor = self.db.users.find({}, {"password_hash": 0, "salt": 0, "_id": 0})
                return list(cursor)
            except Exception:
                pass
        for u in self.local_data.get("users", {}).values():
            res.append(sanitize_user_dict(u))
        return res

    def record_heartbeat(self, player_id: str, hero_class: str, status: str = "active", metadata: dict = None):
        if status == "offline":
            self.record_disconnect(player_id)
            return

        now = time.time()
        record = {
            "player_id": player_id,
            "hero_class": hero_class,
            "status": status,
            "last_ping": now,
            "metadata": metadata or {}
        }
        self._stats_cache = None
        if self.use_mongo:
            try:
                self.db.heartbeats.update_one(
                    {"player_id": player_id},
                    {"$set": record},
                    upsert=True
                )
                self.record_player(player_id, hero_class, metadata)
                return
            except Exception as e:
                print(f"[Database] Mongo heartbeat write error: {e}")

        # Fallback to local
        self.local_data.setdefault("heartbeats", {})[player_id] = record
        self.record_player(player_id, hero_class, metadata)
        self._save_local()

    def record_disconnect(self, player_id: str):
        """Immediately deregister player from active heartbeats upon client exit."""
        self._stats_cache = None
        if self.use_mongo:
            try:
                self.db.heartbeats.delete_one({"player_id": player_id})
                self.db.players.update_one(
                    {"player_id": player_id},
                    {"$set": {"status": "offline", "is_online": False}}
                )
                return
            except Exception as e:
                print(f"[Database] Mongo disconnect write note: {e}")

        # Fallback to local
        self.local_data.get("heartbeats", {}).pop(player_id, None)
        if player_id in self.local_data.get("players", {}):
            self.local_data["players"][player_id]["status"] = "offline"
            self.local_data["players"][player_id]["is_online"] = False
        self._save_local()

    def get_active_players_count(self, threshold_seconds: int = 45) -> int:
        now = time.time()
        cutoff = now - threshold_seconds
        if self.use_mongo:
            try:
                return self.db.heartbeats.count_documents({
                    "last_ping": {"$gte": cutoff},
                    "status": {"$ne": "offline"}
                })
            except Exception:
                pass
        
        hb = self.local_data.get("heartbeats", {})
        return sum(1 for rec in hb.values() if rec.get("last_ping", 0) >= cutoff and rec.get("status") != "offline")

    def get_active_players(self, threshold_seconds: int = 45) -> list:
        now = time.time()
        cutoff = now - threshold_seconds
        if self.use_mongo:
            try:
                cursor = self.db.heartbeats.find({
                    "last_ping": {"$gte": cutoff},
                    "status": {"$ne": "offline"}
                })
                res = []
                for doc in cursor:
                    doc.pop("_id", None)
                    res.append(doc)
                return res
            except Exception:
                pass

        hb = self.local_data.get("heartbeats", {})
        return [rec for rec in hb.values() if rec.get("last_ping", 0) >= cutoff and rec.get("status") != "offline"]

    # ── Player Profile ────────────────────────────────────────────────────────

    def record_player(self, player_id: str, hero_class: str = "Unknown", metadata: dict = None):
        now = time.time()
        update = {
            "player_id": player_id,
            "last_seen": now,
            "last_hero": hero_class,
            "client_env": metadata or {}
        }
        if self.use_mongo:
            try:
                self.db.players.update_one(
                    {"player_id": player_id},
                    {
                        "$set": update,
                        "$setOnInsert": {"first_seen": now, "total_matches": 0, "wins": 0}
                    },
                    upsert=True
                )
                return
            except Exception as e:
                print(f"[Database] Mongo player update error: {e}")

        p = self.local_data.setdefault("players", {}).setdefault(player_id, {
            "player_id": player_id,
            "first_seen": now,
            "total_matches": 0,
            "wins": 0
        })
        p.update(update)

    def update_player_match_stat(self, player_id: str, won: bool, playstyle_persona: str, agent_analysis: dict = None):
        set_fields = {"last_playstyle": playstyle_persona}
        if agent_analysis and agent_analysis.get("playstyle_label"):
            set_fields["last_agent_analysis"] = {
                "playstyle_label": agent_analysis.get("playstyle_label"),
                "playstyle_confidence": agent_analysis.get("playstyle_confidence"),
                "playstyle_reasoning": agent_analysis.get("playstyle_reasoning"),
                "strengths": agent_analysis.get("strengths", []),
                "weaknesses": agent_analysis.get("weaknesses", []),
                "coaching_tip": agent_analysis.get("coaching_tip"),
                "agent_summary": agent_analysis.get("agent_summary"),
                "counter_play_grade": agent_analysis.get("counter_play_grade"),
                "risk_profile": agent_analysis.get("risk_profile"),
                "resource_management": agent_analysis.get("resource_management"),
                "combo_usage": agent_analysis.get("combo_usage"),
                "missed_opportunities": agent_analysis.get("missed_opportunities", []),
                "key_moment": agent_analysis.get("key_moment"),
            }
        if self.use_mongo:
            try:
                inc = {"total_matches": 1}
                if won:
                    inc["wins"] = 1
                self.db.players.update_one(
                    {"player_id": player_id},
                    {
                        "$inc": inc,
                        "$set": set_fields
                    }
                )
                return
            except Exception as e:
                print(f"[Database] Mongo player stat error: {e}")

        p = self.local_data.setdefault("players", {}).setdefault(player_id, {
            "player_id": player_id,
            "first_seen": time.time(),
            "total_matches": 0,
            "wins": 0
        })
        p["total_matches"] = p.get("total_matches", 0) + 1
        if won:
            p["wins"] = p.get("wins", 0) + 1
        for k, v in set_fields.items():
            p[k] = v

    # ── Matches ───────────────────────────────────────────────────────────────

    def save_match(self, match_data: dict, commit: bool = True) -> dict:
        summary = match_data.get("summary", {})
        player_id = summary.get("player_id") or match_data.get("player_id") or "unknown_player"
        match_id = summary.get("match_id") or match_data.get("match_id")
        outcome = summary.get("outcome") or match_data.get("outcome")
        won = (outcome == "win")
        
        pred = match_data.get("prediction") or summary.get("prediction") or {}
        persona = pred.get("persona", "Unknown")

        # Grab agent_analysis from payload or summary
        agent_analysis = (
            match_data.get("agent_analysis")
            or summary.get("agent_analysis")
            or {}
        )

        doc = {
            "match_id": match_id,
            "player_id": player_id,
            "hero_class": summary.get("hero_class") or match_data.get("hero_class"),
            "boss_variant": summary.get("boss_variant") or match_data.get("boss_variant"),
            "outcome": outcome,
            "total_turns": summary.get("total_turns") or match_data.get("total_turns"),
            "prediction": pred,
            "agent_analysis": agent_analysis,
            "summary": summary,
            "client_metadata": match_data.get("client_metadata", {}),
            "created_at": time.time(),
            "created_at_iso": datetime.now().isoformat()
        }

        # Include turn data if present for Federated Learning
        if "turns" in match_data:
            doc["turns"] = match_data["turns"]

        if self.use_mongo:
            try:
                self.db.matches.insert_one(doc)
                self.update_player_match_stat(player_id, won, persona, agent_analysis)
                doc.pop("_id", None)
                return doc
            except Exception as e:
                print(f"[Database] Mongo match insert error: {e}")

        # Local storage fallback
        matches = self.local_data.setdefault("matches", [])
        # Prevent duplicate inserts
        matches = [m for m in matches if m.get("match_id") != doc.get("match_id")]
        matches.insert(0, doc)
        self.local_data["matches"] = matches
        self.update_player_match_stat(player_id, won, persona, agent_analysis)
        if commit:
            self._save_local()
        return doc

    def get_matches(self, limit: int = 50) -> list:
        if self.use_mongo:
            try:
                cursor = self.db.matches.find({}, {"turns": 0}).sort("created_at", -1).limit(limit)
                res = []
                for doc in cursor:
                    doc.pop("_id", None)
                    res.append(doc)
                return res
            except Exception as e:
                print(f"[Database] Mongo matches query error: {e}")

        return self.local_data.get("matches", [])[:limit]

    def get_all_matches_raw(self) -> list:
        """Returns all matches with turns for Federated Learning."""
        if self.use_mongo:
            try:
                cursor = self.db.matches.find({})
                res = []
                for doc in cursor:
                    doc.pop("_id", None)
                    res.append(doc)
                return res
            except Exception as e:
                print(f"[Database] Mongo raw query error: {e}")

        return self.local_data.get("matches", [])

    # ── Players ───────────────────────────────────────────────────────────────

    def get_players(self) -> list:
        active_ids = {p.get("player_id") for p in self.get_active_players()}
        if self.use_mongo:
            try:
                cursor = self.db.players.find({}).sort("last_seen", -1)
                res = []
                for doc in cursor:
                    doc.pop("_id", None)
                    doc["is_online"] = (doc.get("player_id") in active_ids)
                    res.append(doc)
                return res
            except Exception as e:
                print(f"[Database] Mongo players query error: {e}")

        players = []
        for p in self.local_data.get("players", {}).values():
            p_copy = dict(p)
            p_copy["is_online"] = (p_copy.get("player_id") in active_ids)
            players.append(p_copy)
        players.sort(key=lambda x: x.get("last_seen", 0), reverse=True)
        return players

    # ── Federated Learning Rounds ─────────────────────────────────────────────

    def save_fl_round(self, round_data: dict):
        if self.use_mongo:
            try:
                self.db.fl_rounds.insert_one(round_data)
                round_data.pop("_id", None)
                return
            except Exception as e:
                print(f"[Database] Mongo fl_round insert error: {e}")

        fl_rounds = self.local_data.setdefault("fl_rounds", [])
        fl_rounds.append(round_data)
        self._save_local()

    def get_fl_rounds(self) -> list:
        if self.use_mongo:
            try:
                cursor = self.db.fl_rounds.find({}).sort("round_number", 1)
                res = []
                for doc in cursor:
                    doc.pop("_id", None)
                    res.append(doc)
                return res
            except Exception as e:
                print(f"[Database] Mongo fl_rounds query error: {e}")

        return self.local_data.get("fl_rounds", [])

    # ── Dashboard Statistics ──────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Global metrics for monitoring dashboard."""
        now = time.time()
        if self._stats_cache and (now - self._stats_cache_time < 2.5):
            return self._stats_cache

        active = self.get_active_players()
        matches = self.get_matches(limit=500)
        players = self.get_players()

        total_matches = len(matches)
        wins = sum(1 for m in matches if m.get("outcome") == "win")
        win_rate = round((wins / total_matches) * 100, 1) if total_matches > 0 else 0.0

        personas = {}
        for m in matches:
            p = m.get("prediction", {}).get("persona") or "Unknown"
            personas[p] = personas.get(p, 0) + 1

        heroes = {}
        for m in matches:
            h = m.get("hero_class") or "Unknown"
            heroes[h] = heroes.get(h, 0) + 1

        res = {
            "active_players_count": len(active),
            "total_players_count": len(players),
            "total_users_count": len(self.get_all_users()),
            "total_matches_count": total_matches,
            "win_rate": win_rate,
            "playstyle_distribution": personas,
            "db_mode": "MongoDB" if self.use_mongo else "Local Cache",
            "active_players": active,
        }
        self._stats_cache = res
        self._stats_cache_time = now
        return res

    def import_logs_directory(self, logs_dir: str = None):
        """Scans logs directory and imports matches with predictions if DB is empty or for initial sync."""
        if len(self.get_matches(limit=1)) > 0:
            return

        if logs_dir is None:
            logs_dir = os.path.join(_ROOT_DIR, "logs")
        if not os.path.isdir(logs_dir):
            return

        try:
            from model.predictor import predict_match
        except Exception:
            predict_match = lambda d: None

        imported = 0
        for root, _, files in os.walk(logs_dir):
            for file in files:
                if file.startswith("match_") and file.endswith(".json"):
                    fpath = os.path.join(root, file)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        summary = data.get("summary", {})
                        match_id = summary.get("match_id")
                        if not match_id:
                            continue
                        
                        existing = [m for m in self.get_matches(limit=1000) if m.get("match_id") == match_id]
                        if existing:
                            continue

                        pred = data.get("prediction") or (predict_match(data) if predict_match else None)
                        data["prediction"] = pred
                        data["client_metadata"] = data.get("client_metadata") or {
                            "os": "Windows", "game_version": "2.0-fl", "imported": True
                        }
                        self.save_match(data, commit=False)
                        imported += 1
                    except Exception:
                        pass
        if imported > 0:
            if not self.use_mongo:
                self._save_local()
            print(f"[Database] Pre-loaded {imported} matches from {logs_dir} into database.")

_GLOBAL_DB = None

def get_db() -> Database:
    global _GLOBAL_DB
    if _GLOBAL_DB is None:
        _GLOBAL_DB = Database()
    return _GLOBAL_DB
