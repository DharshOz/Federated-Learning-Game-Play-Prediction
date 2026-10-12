"""
server.py — FastAPI Backend Server & Federated Learning Orchestrator.

Provides the REST API for:
1. Universal game client telemetry (heartbeats and post-match log ingestion).
2. MongoDB / resilient local database querying.
3. Federated Learning round execution (FedAvg across client match partitions).
4. Serving the real-time web monitoring and FL visualizer dashboard.
"""

import os
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from dotenv import load_dotenv

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

from backend.db import get_db

try:
    from model.federated_engine import get_fl_coordinator, FL_GLOBAL_PATH, MODEL_PATH
except Exception:
    get_fl_coordinator = lambda: None
    FL_GLOBAL_PATH = os.path.join(_ROOT_DIR, "fl_global_model.pt")
    MODEL_PATH = os.path.join(_ROOT_DIR, "playstyle_classifier.pt")

app = FastAPI(title="Arcane Clash Federated Learning Observatory", version="2.0")

# Enable CORS for universal multi-client connectivity
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = get_db()
fl_coord = get_fl_coordinator() if callable(get_fl_coordinator) else None


@app.on_event("startup")
def startup_event():
    import threading
    def _bg_import():
        try:
            db.import_logs_directory()
        except Exception as e:
            print(f"[Server] Startup import note: {e}")
    threading.Thread(target=_bg_import, daemon=True, name="StartupLogsImport").start()

# ── Web Interface ─────────────────────────────────────────────────────────────

@app.get("/favicon.ico")
async def favicon():
    return JSONResponse({}, status_code=204)

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    # Check dashboard/templates/index.html, then templates/index.html
    candidate_paths = [
        os.path.join(_ROOT_DIR, "dashboard", "templates", "index.html"),
        os.path.join(_ROOT_DIR, "templates", "index.html"),
        os.path.join(os.path.dirname(__file__), "..", "dashboard", "templates", "index.html"),
        os.path.join(os.path.dirname(__file__), "..", "templates", "index.html"),
    ]
    for tmpl_path in candidate_paths:
        if os.path.exists(tmpl_path):
            with open(tmpl_path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
    return HTMLResponse("<h2>Arcane Clash Dashboard template not found.</h2>", status_code=404)

@app.get("/api/overview")
def get_overview():
    """Consolidated endpoint delivering stats, recent matches, and players in a single call."""
    return {
        "stats": db.get_stats(),
        "matches": db.get_matches(limit=50),
        "players": db.get_players(),
        "users": db.get_all_users()
    }

# ── User Authentication Endpoints ─────────────────────────────────────────────

@app.post("/api/auth/register")
async def register_account(req: Request):
    """Register a new player account with username and password."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    username = body.get("username", "")
    password = body.get("password", "")

    success, msg, user_data = db.register_user(username, password)
    if not success:
        return JSONResponse({"status": "error", "message": msg}, status_code=400)
    return {"status": "success", "message": msg, "user": user_data}

@app.post("/api/auth/login")
async def login_account(req: Request):
    """Authenticate player credentials and return active user profile."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    username = body.get("username", "")
    password = body.get("password", "")

    success, msg, user_data = db.authenticate_user(username, password)
    if not success:
        return JSONResponse({"status": "error", "message": msg}, status_code=401)
    return {"status": "success", "message": msg, "user": user_data}

@app.get("/api/auth/users")
def get_registered_users():
    """List all registered players."""
    return {"users": db.get_all_users()}

@app.get("/api/auth/user/{username}")
def get_user_profile(username: str):
    """Get single user profile and stats."""
    u = db.get_user(username)
    if not u:
        return JSONResponse({"status": "error", "message": "User not found"}, status_code=404)
    # Also fetch player stats if present
    players = db.get_players()
    p_stat = next((p for p in players if p.get("player_id") == username), {})
    return {"status": "success", "user": u, "stats": p_stat}

@app.get("/api/user/{username}/matches")
def get_user_matches(username: str, limit: int = 50):
    """Retrieve match logs belonging to a specific player."""
    all_m = db.get_matches(limit=500)
    user_m = [m for m in all_m if m.get("player_id") == username or m.get("summary", {}).get("player_id") == username]
    return {"username": username, "total": len(user_m), "matches": user_m[:limit]}

# ── Game Telemetry Endpoints ──────────────────────────────────────────────────

@app.post("/api/heartbeat")
async def post_heartbeat(req: Request):
    """Universal ping endpoint sent periodically by active game clients."""
    try:
        data = await req.json()
        pid = data.get("player_id", "anonymous")
        hero = data.get("hero_class", "Unknown")
        status = data.get("status", "playing")
        meta = data.get("metadata", {})
        db.record_heartbeat(pid, hero, status, meta)
        return {"status": "ok", "timestamp": time.time()}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)

@app.post("/api/heartbeat/disconnect")
async def post_disconnect(req: Request):
    """Immediately deregister a player from active heartbeats upon game closure."""
    try:
        data = await req.json()
        pid = data.get("player_id")
        if pid:
            db.record_disconnect(pid)
        return {"status": "ok", "player_id": pid}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)

@app.post("/api/matches")
async def post_match(req: Request):
    """Receives completed match telemetry with predictions and metadata."""
    try:
        data = await req.json()
        saved = db.save_match(data)
        return {"status": "success", "match_id": saved.get("match_id")}
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)

# ── Monitoring & Analytics ────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats():
    """Global KPIs for the monitoring header."""
    return db.get_stats()

@app.get("/api/matches")
def get_matches(limit: int = 50):
    """Recent matches list with AI predictions."""
    return db.get_matches(limit=limit)

@app.get("/api/players")
def get_players():
    """All players who have connected or played."""
    return db.get_players()

# ── Agent Analysis Endpoints ──────────────────────────────────────────────────

@app.post("/api/agent/analyse")
async def agent_analyse(req: Request):
    """
    On-demand playstyle analysis by the Groq agent.
    Accepts a match payload (same format as /api/matches POST) and returns insight JSON.
    """
    try:
        data = await req.json()
        from backend.playstyle_agent import analyse_match
        ml_pred = data.get("prediction") or data.get("summary", {}).get("prediction")
        result = analyse_match(data, ml_pred)
        return result
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)

@app.get("/api/player/{player_id}/agent_analysis")
def get_player_agent_analysis(player_id: str):
    """Return the latest stored agent analysis for a player."""
    players = db.get_players()
    for p in players:
        if p.get("player_id") == player_id:
            return {
                "player_id": player_id,
                "last_agent_analysis": p.get("last_agent_analysis"),
                "last_playstyle": p.get("last_playstyle"),
            }
    return JSONResponse({"error": "Player not found"}, status_code=404)

# ── Federated Learning Controls ───────────────────────────────────────────────

@app.get("/api/fl/status")
def get_fl_status():
    rounds = db.get_fl_rounds()
    return {
        "global_model_version": "2.0-FedAvg",
        "rounds_completed": len(rounds),
        "last_round": rounds[-1] if rounds else None,
        "history": rounds
    }

@app.post("/api/fl/train_round")
async def train_fl_round(req: Request):
    """
    Executes a Federated Learning round (FedAvg) across private player match partitions.
    Incorporate Differential Privacy perturbations and updates the global model.
    """
    try:
        body = await req.json()
    except Exception:
        body = {}

    epochs = int(body.get("local_epochs", 3))
    eps = float(body.get("epsilon", 1.5))
    lr = float(body.get("lr", 0.005))

    matches = db.get_all_matches_raw()
    if fl_coord is None:
        return JSONResponse({"status": "error", "message": "Federated coordinator not available"}, status_code=500)

    result = fl_coord.train_federated_round(
        matches=matches,
        local_epochs=epochs,
        epsilon_dp=eps,
        lr=lr
    )

    if result.get("success"):
        round_idx = len(db.get_fl_rounds()) + 1
        result["round_number"] = round_idx
        db.save_fl_round(result)

    return result

@app.get("/api/fl/download_model")
async def download_model():
    """Download the federated global model checkpoint."""
    path = FL_GLOBAL_PATH if os.path.exists(FL_GLOBAL_PATH) else MODEL_PATH
    if os.path.exists(path):
        return FileResponse(path, filename="arcane_clash_global_model.pt", media_type="application/octet-stream")
    return JSONResponse({"error": "No model file found"}, status_code=404)

def run_server(host: str = None, port: int = None):
    if host is None:
        host = os.getenv("HOST", "0.0.0.0")
    if port is None:
        port = int(os.getenv("PORT", 8000))

    print("============================================================")
    print("ARCANE CLASH FEDERATED LEARNING SERVER & OBSERVATORY")
    print("============================================================")
    print(f"Dashboard URL : http://localhost:{port}")
    print(f"API Base      : http://localhost:{port}/api")
    print(f"Listening on  : {host}:{port}")
    uvicorn.run(app, host=host, port=port, timeout_keep_alive=65, access_log=False)

if __name__ == "__main__":
    run_server()
