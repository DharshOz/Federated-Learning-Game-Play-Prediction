# Arcane Clash ⚔️🔮 – Turn-Based Wizard RPG (v2.0)

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Pygame](https://img.shields.io/badge/Pygame-2.0+-green?style=for-the-badge&logo=python)](https://www.pygame.org/)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Active%20Development-gold?style=for-the-badge)]()

**Arcane Clash** is a strategic, turn-based fantasy RPG developed in Python using **Pygame**. Step into the boots of powerful elemental wizards, balance your health, XP, and mystical power reserves, and wage tactical battle against towering Minotaur beasts across dynamic arenas.

---

## 🌟 Key Features

- **🧙‍♂️ Diverse Hero Classes**: Choose between specialized spellcasters—the high-damage **Fire Wizard**, the lightning-quick **Lightning Mage**, or the versatile and resilient **Wanderer Magician**.
- **🐂 Adaptive AI Opponents & Telegraphing**: Battle Minotaur bosses (**Minotaur Ⅰ, Ⅱ, Ⅲ**) that telegraph their upcoming attacks one turn in advance (with a 20% feint chance to keep battles unpredictable).
- **⏳ Spell Cooldowns & Tactical Planning**: High-impact spells like **Fireball** and **Fire Spell** feature a 3-turn cooldown, demanding thoughtful decision timing over spamming.
- **🛡️ Soft Counter Relationships**: Reward reading enemy intent—mitigate telegraphed strikes with **Water Arrow** (65% damage reduction) or absorb heavy spells with **Rest & Recharge** (60% Perfect Guard absorption).
- **📊 ML-Ready Playstyle Data Logging**: Decoupled local telemetry layer (`logger.py`) that captures per-turn decisions, reaction times, counter-play accuracy, and match summaries under `/logs/{player_id}/` for federated learning and analytics.
- **💎 Multi-Tier Power Mechanics**:
  - **Resource Currency**: High-tier spells consume Power and XP.
  - **Passive Defense**: Every 10 Power points above 40 provides a 2% damage reduction (up to 25%).
  - **Offensive Scaling**: Every 10 Power points above 50 yields a 2% outgoing damage bonus (up to 20%).
- **🔥 Status Ailments & Buffs**: Inflict and endure **Burning** (DoT), **Exhaustion** (-25% accuracy), **Weakened** (-40% to -65% damage), and **Shield Defense** (+35% to +60% damage reduction from Rest).
- **🎨 Premium Visual & UI Design**:
  - Smooth multi-frame sprite sheet animations: *Idle, Attack 1, Attack 2, Charge, Hurt, Dying, and Taunts*.
  - Elemental spell VFX animations (Fireballs, Fire Arrows, Fire Spells, Water Arrows, Water Spells).
  - Floating combat text with alpha fadeouts.
  - Interactive combat log recording turn events.
  - Ability hover tooltips detailing costs, hit rates, and status effects.
  - Floating ambient particle systems on menus and arena selection.
- **🗺️ Arena Selection**: Choose from 8 detailed high-resolution fantasy backdrops or the classic city arena.

---

## 📸 Screenshots & Previews

| Main Menu & Setup | Battle Arena |
| :---: | :---: |
| ![Main Menu](./Screenshots/ss1.png) | ![Combat Demo](./Screenshots/ss2.png) |

---

## 🧙‍♂️ Playable Heroes

| Hero | Base HP | Base ATK | Specialization & Playstyle |
| :--- | :---: | :---: | :--- |
| **Fire Wizard** | 120 | 14 | **High Damage / Fire Mastery**: Unleashes scorching fireballs and devastating finishing spells. Must monitor exhaustion. |
| **Lightning Mage** | 100 | 16 | **Precision Glass Cannon**: High offensive output and agility. Demands careful health management. |
| **Wanderer Magician** | 110 | 12 | **Resilient & Balanced**: Sturdy defensive baseline, adaptable to both attrition and burst strategies. |

---

## 🐂 Boss Villains

- **Minotaur Ⅰ, Ⅱ, Ⅲ**: Towering brutes boasting 130 HP with an adaptive attack rotation. They can cast elemental arrows, burst fire, and use *Rest & Recharge* when their energy runs low.

---

## 📜 The Spellbook (Combat Actions)

| Ability | Base Dmg | Hit Chance | Cost | Cooldown | Effects & Modifiers |
| :--- | :---: | :---: | :---: | :---: | :--- |
| ⚔️ **Quick Slash** | 12 | 90% | 5 XP / 8 Power | 0 Turns | Reliable fast strike. 4th consecutive hit triggers *Flurry Finisher*! |
| 🔥 **Fireball** | 28 | 70% | 20 XP / 25 Power | 3 Turns | Heavy flame; inflicts **Burning** (doubled to 16 HP/turn via *Soaked Ignition* combo). |
| 💧 **Water Arrow** | 18 | 80% | 12 XP / 15 Power | 0 Turns | Piercing shot; **Weakens** enemy (-40% normal / -65% vs telegraphed strikes). Sets up *Soaked Ignition*. |
| 🌊 **Water Spell** | 22 | 65% | 18 XP / 20 Power | 0 Turns | Risky torrent; restores **+10 HP** to caster on a successful hit. |
| ☄️ **Fire Spell** | 35 | 55% | 30 XP / 35 Power | 3 Turns | Cataclysmic blast; deals **3x Damage** if XP > 80. Self-recoil waived via *Channelled Inferno* combo! |
| ❤️ **Heal** | — | 100% | 10 XP / 0 Power | 0 Turns | Restores **25 HP** and **+15 Power**. Never misses. |
| 🛡️ **Rest & Recharge** | — | 100% | Free (0/0) | 0 Turns | Recovers **+20 XP** and **+25 Power**; raises shield (**35% normal / 60% Perfect Guard**). Sets up *Channelled Inferno*. |
| 💢 **Enrage** *(Boss Only)* | 26 | 85% | 15 XP / 20 Power | 0 Turns | Unlocked in Phase 2. Ferocious enraged slam dealing heavy physical damage. |

---

## ⚡ Cross-Turn Combo Chains

Decisions carry forward-looking weight through cross-turn action chaining:

| Combo Name | Trigger Sequence | Combo Bonus Effect |
| :--- | :--- | :--- |
| 🌊🔥 **Soaked Ignition** | `Water Arrow` (hit) ➔ `Fireball` (next turn) | **Doubles Fireball's Burning DoT** to 16 HP/turn for its full 2-turn duration. |
| ⚔️⚡ **Flurry Finisher** | `Quick Slash` x3 ➔ `Quick Slash` (4th turn) | **Guaranteed Hit** (100% accuracy) and **+50% Critical Damage**. Resets if broken. |
| 🛡️☄️ **Channelled Inferno** | `Rest & Recharge` ➔ `Fire Spell` (next turn) | **Completely waives Fire Spell's 20 HP self-recoil damage** (0 HP lost). |

---

## 🐂 Boss Phase Transitions & Adaptive Memory

### Boss Phase Shifts
The Minotaur dynamically alters its behavior and telegraphing across 3 distinct HP thresholds:
- **Phase 1 (100%–66% HP)**: Standard tactical rotation with honest telegraphs and a 20% feint chance.
- **Phase 2 (65%–33% HP) — Enraged**: Unlocks the high-damage **Enrage** slam. Every 3rd turn, the boss masks its telegraph completely, displaying `??? (MASKED)` to the player.
- **Phase 3 (32%–0% HP) — Desperation**: Feint rate doubles to **40%**. Boss becomes desperate and faltering, reducing all its outgoing damage by **15%**.
- *Transitions occur exactly once per threshold with boss taunt animations and screen alert banners.*

### In-Match Adaptive Memory (`adaptive_weighting.py`)
The boss tracks a rolling history of the player's last 5 actions within the current match:
- **Anti-Turtle Counter**: If the player chooses defensive moves (`Rest`, `Heal`) 3+ times in 5 turns, the boss increases its probability of selecting Guard-breaking / heavy attacks (`Enrage`, `Fireball`, `Fire Spell`) by **+25%**.
- **Anti-Aggro Counter**: If the player attacks aggressively 3+ times in 5 turns, the boss increases its probability of using `Rest & Recharge` / shielding by **+25%**.
- Probabilities are dynamically normalized and snapshot into the ML log per turn.

---

## 📂 Project Architecture

```
Python-Pygame-Turn-Based-RPG-/
├── Assets/                 # Fonts (Joystix), classic background, and sound assets
├── attack effects/         # Frame-by-frame PNG sequences for spell projectiles
│   ├── Fire Ball/ ... Water Spell/
├── game/                   # 🎮 Game Module
│   ├── game.py             # Game loop, state machine, combo detector, phase manager
│   ├── entity.py           # RPG stats, combos, phase shifts, AI telegraphing & soft counters
│   ├── ui.py               # UI rendering, HUDs, buttons, endscreen, tooltips
│   ├── animation.py        # Animation controller, frame timers & projectile effects
│   ├── spritesheet.py      # Spritesheet slicing utilities
│   ├── adaptive_weighting.py # In-match adaptive boss memory & rolling action weighting
│   └── logger.py           # Telemetry logger & post-match AI prediction trigger
├── backend/                # ⚙️ Backend Module
│   ├── server.py           # FastAPI backend & Federated Learning orchestrator
│   ├── db.py               # MongoDB storage layer with resilient local cache fallback
│   ├── client_sync.py      # Universal background heartbeat & match telemetry dispatcher
│   └── server_manager.py   # Automatic server lifecycle & browser observatory launch
├── dashboard/              # 📊 Dashboard Module
│   ├── templates/index.html# Real-time web observatory & FL visualizer
│   └── dashboard_app.py    # Direct dashboard launcher
├── model/                  # 🧠 Model & ML Module
│   ├── model.py            # PyTorch PlaystyleClassifier neural network
│   ├── predictor.py        # Real-time PyTorch PlaystyleClassifier inference engine
│   ├── extract_features.py # 49-feature extraction pipeline (Groups A-I)
│   ├── federated_engine.py # FedAvg algorithm with Differential Privacy (ε)
│   ├── train_centralized.py# Centralized baseline model trainer & leakage checker
│   ├── persona_bots.py     # Synthetic gameplay bots generator
│   ├── cluster_labels.py   # Unsupervised KMeans clustering & silhouette analysis
│   └── playstyle_classifier.pt # Trained model checkpoint
├── backgrounds/            # 8 high-resolution arena backdrops (2304x1296)
├── GUI/                    # UI elements, buttons, and HUD templates
├── Screenshots/            # Project showcase images
├── logs/                   # Local client ML playstyle telemetry (JSON per match)
│   └── {player_id}/        # Partitioned per local client for privacy / FL pipelines
├── villans/                # Minotaur sprite sequences (Idle, Attacking, Hurt, Dying, Taunt)
├── wizards heros/          # Wizard sprite sheets (Fire, Lightning, Wanderer)
├── game.py                 # 🚀 Root Game Launcher (auto-launches dashboard)
├── server.py               # 🚀 Root Backend Server Launcher
├── dashboard.py            # 🚀 Root Standalone Dashboard Launcher
├── .env                    # MongoDB URI, backend URL, and FL hyperparameters
├── .env.example            # Environment template for repository clones
├── requirements.txt        # Python dependency manifest
└── README.md               # Project documentation
```

---

## 🔮 Post-Match AI Playstyle Classification

Whenever a match concludes in **Victory** or **Defeat**:
1. The game immediately extracts 49 behavioral features from the match decisions.
2. The trained PyTorch [`PlaystyleClassifier`](file:///d:/9th%20SEM/CAT2%20PROJECT/DATA%20PRIVACY/Python-Pygame-Turn-Based-RPG-/model.py) and `StandardScaler` evaluate the player's attack patterns.
3. A sleek, animated **AI Archetype Card** is rendered right on the end screen, showing:
   - **Archetype**: `⚔️ Relentless Berserker [AGGRESSIVE]`, `🛡️ Tactical Guardian [DEFENSIVE]`, `⚡ Grand Strategist [OPTIMAL]`, or `🎲 Wildcard Sorcerer [RANDOM]`.
   - **Confidence Percentage** (e.g. `96.4% MATCH`).
   - **Tactical Rationale**: Explanation of the player's habits.
   - **Metrics Grid**: Counter-play rate, damage trade ratio, action entropy, and average reserves.

---

## 🌐 Universal Telemetry & MongoDB Backend

Arcane Clash is built so **anyone who clones this repository** from GitHub can play locally while having their gameplay telemetry monitored and fed into the Federated Learning pipeline:

### 1. Configure `.env`
Edit `.env` (or copy from `.env.example`):
```env
# MongoDB Atlas Cloud or Local Instance
MONGODB_URI=mongodb+srv://<user>:<password>@cluster.mongodb.net/arcane_clash
MONGODB_DB_NAME=arcane_clash

# Central Observatory Server URL (Host's public URL or localhost)
BACKEND_URL=http://localhost:8000
```
*Note: If MongoDB is not yet running or credentials are blank, the backend automatically uses a resilient local cache (`backend_storage.json`) so the game and server never crash.*

### 2. Start the Game & Live Dashboard
```bash
python game.py
```
- The game automatically launches the backend server in the background.
- As you play, periodic heartbeats update the **"Players Online Right Now"** live counter.
- When your match concludes (**Victory** or **Defeat**), the full match payload, client metadata, extracted features, and predicted playstyle are synced to MongoDB, and the **live dashboard automatically opens in your browser**!
- You can also click **`[ 📊 Live Dashboard ]`** directly from the in-game Main Menu or Victory/Defeat screen anytime!

### 3. Standalone Dashboard / Server (Optional)
```bash
# Direct launcher to open the web observatory in your default browser:
python dashboard.py

# Or run the FastAPI server standalone:
python server.py
```

---

## 🏛️ Federated Learning Hub & Web Visualizer

The web observatory at `http://localhost:8000` provides:
- **🟢 Live Player Tracking**: Real-time counter of combatants active in the last 45 seconds with instant logout detection.
- **⚔️ Live Match Stream**: Real-time feed of completed matches with hero vs boss, win/loss pills, ML classification badges, and Groq LLM coaching strips.
- **👥 Player Directory**: Database of all unique registered players, win rates, dominant styles, and detailed AI insights.
- **⚡ Federated Learning Coordinator**:
  - **FedAvg Execution**: Runs federated averaging rounds across private player data partitions.
  - **Differential Privacy (DP)**: Adjustable $\epsilon$ privacy budget and gradient clipping.
  - **Convergence Graphs**: Real-time loss and test accuracy curves across rounds.
  - **Download Global Weights**: Download the updated `arcane_clash_global_model.pt` directly from the UI.

---

## 🤖 Phase 3: Groq LLM Playstyle Coaching Agent

In addition to the neural classifier (`playstyle_classifier.pt`), matches are evaluated by an autonomous AI agent powered by **Groq** (`llama-3.3-70b-versatile`):
- **Full Game Mechanics Context**: System prompt embeds all spell rules, damage math, passive mitigation thresholds, combo chains (Soaked Ignition, Flurry Finisher, Channelled Inferno), and boss telegraphing heuristics.
- **Context Filtering**: High-frequency internal physics/asset state variables are stripped; key strategic events (phase transitions, low HP saves, combo triggers, telegraph counters) are intelligently sampled.
- **Structured Strategic Insights**:
  - `playstyle_label` & `playstyle_confidence` (Optimal, Aggressive, Defensive, Random)
  - `counter_play_grade` (A/B/C/D/F rating based on telegraph responses)
  - `resource_management` assessment (XP and Power efficiency)
  - `risk_profile` (Reckless, Balanced, Cautious)
  - `coaching_tip` (Tailored, actionable tip rendered on the game-over screen and dashboard)
  - `key_moment` & `missed_opportunities`
- **Dual SDK / REST Resilience**: Automatically leverages either `groq` SDK or direct HTTP requests via `requests`/`httpx`.

---

## 💡 Gameplay & Strategy Tips

- **Manage your Power Bar**: Don't deplete all your Power in the opening turn! Keeping your Power above 50 boosts your spell damage by up to 20%, and keeping it above 40 grants up to 25% passive damage mitigation.
- **Combos with Status Effects**:
  - Open with **Water Arrow** to weaken the enemy's attack before they unleash a heavy strike.
  - Apply **Fireball** early to let the burn damage chip away at the boss's health bar over multiple turns.
- **High-Risk, High-Reward**: Save your XP to exceed 80, then strike with **Fire Spell** for an immense 3x damage burst. Just be sure your HP can handle the self-recoil!
- **Shielding**: When you predict a heavy hit from the enemy or need resources, choose **Rest & Recharge** to brace for 35% less incoming damage while regaining XP and Power.

---

## 🎨 Asset Credits

- Sprite Sheets, Character Animations, and Arenas sourced from [CraftPix.net](https://craftpix.net/) (free game assets license).
- Monospace font: **Joystix** by Ray Larabie (Typodermic Fonts).
- Built with [Pygame](https://www.pygame.org/) and [FastAPI](https://fastapi.tiangolo.com/).

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) – feel free to modify, extend, and build upon it for learning and personal projects!

