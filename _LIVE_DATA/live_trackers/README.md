# Live Trackers v1.3

Real-time leverage node monitoring system for [The Regulated Friction Project](https://github.com/Leerrooy95/The_Regulated_Friction_Project).

Tracks seven active leverage nodes — Maxwell, Iran, Gulf SWFs, Israel, Oracle/Ellison, Epstein Files, and Arkansas Datacenter Nexus — using a three-stage pipeline: Perplexity Sonar Pro for real-time intelligence, Llama Scout 17B for structured entity extraction, and local convergence detection to flag multi-node activity windows.

**Author:** Austin Smith | 19D Cavalry Scout (OSINT Methodology)

---

## Architecture

```
┌─────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│   node_tracker.py   │────▶│  entity_extractor.py │────▶│convergence_detector.py│
│   (Perplexity Pro)  │     │   (Llama Scout 17B)  │     │   (Local Analysis)   │
└─────────────────────┘     └──────────────────────┘     └──────────────────────┘
         │                           │                            │
         ▼                           ▼                            ▼
  node_status.json          extracted_entities.json       convergence_report.json
```

**Stage 1 — Node Tracker:** Queries Perplexity sonar-pro for the current status of each leverage node. Classifies events as FRICTION, COMPLIANCE, ESCALATION, or DE_ESCALATION.

**Stage 2 — Entity Extractor:** Sends node status reports to Llama-4-Scout-17B for structured extraction — named entities, relationships, temporal markers, and cross-node connections.

**Stage 3 — Convergence Detector:** Reads historical tracker runs and detects convergence patterns — windows where 3+ nodes show simultaneous activity, consistent with the thermostat model's 7-day convergence window.

---

## Leverage Nodes

| Node | Type | What It Tracks |
|------|------|----------------|
| `maxwell` | Information | Clemency negotiations, House Oversight, 5th Amendment invocation, habeas corpus petition |
| `iran` | Kinetic | US-Iran war status, Khamenei succession, Strait of Hormuz closure, Iran retaliation, energy crisis |
| `gulf_swf` | Capital | PIF, Mubadala, MGX positioning under wartime stress, Strait of Hormuz energy impact on $4.9T AUM |
| `israel` | Kinetic | Cyber/intelligence operations, Lebanon front, Abraham Accords capital bridge, Board of Peace |
| `oracle_ellison` | Capital | Oracle financial stress ($45-50B raise), Stargate contraction, Ellison WBD guarantee |
| `epstein_files` | Information | DOJ releases, FBI 302 interview summaries, Congressional subpoenas, Clinton depositions |
| `arkansas_datacenter` | Capital | State-level preemption (Good Day Farm), $17B+ datacenter deployment, utility rate capture |

---

## Quick Start

### Prerequisites

```bash
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file (never commit this):

```
PERPLEXITY_API_KEY=your_key_here
LLAMA_SCOUT_KEY=your_key_here
```

### Run

```bash
# Full pipeline (all three stages)
chmod +x run_pipeline.sh
./run_pipeline.sh

# Individual stages
python node_tracker.py                 # Stage 1 only
python entity_extractor.py             # Stage 2 only (requires Stage 1 output)
python convergence_detector.py         # Stage 3 only (requires Stage 1 history)

# Single node
python node_tracker.py --node maxwell

# Dry run (preview queries)
python node_tracker.py --dry-run
```

---

## Output

| File | Content |
|------|---------|
| `output/node_status.json` | Current status of all tracked nodes (overwritten each run) |
| `output/extracted_entities.json` | Structured entities, relationships, and cross-node connections |
| `output/convergence_report.json` | Multi-node convergence analysis with friction/compliance pairs |
| `output/history/tracker_*.json` | Timestamped copies of every tracker run |
| `output/history/extraction_*.json` | Timestamped copies of every extraction run |

---

## Streamlit Dashboard

The project includes a professional Streamlit dashboard for visualizing tracker data in real time.

```bash
# Run locally
streamlit run streamlit_app.py
```

The dashboard shows:
- **Node Status** — Live status cards with classification badges and confidence levels
- **Entity Extraction** — Structured entities, relationships, and cross-node connections
- **Convergence Analysis** — Multi-node convergence windows and friction/compliance pairs
- **Run History** — Browse historical pipeline runs
- **Pipeline Controls** — Dry-run previews from the UI

---

## Deployment

Everything runs through **GitHub Actions** — no external servers required:

1. **Push to `main`** → validates code, checks for secrets, compiles pipeline scripts
2. **Scheduled pipeline** → runs the tracker pipeline twice daily (08:00 / 20:00 UTC)
3. **Manual trigger** → run either workflow on-demand from the **Actions** tab

See [`SETUP.md`](SETUP.md) for complete configuration instructions.

### Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `PERPLEXITY_API_KEY` | Perplexity API key (for Stage 1 — Node Tracker) |
| `LLAMA_SCOUT_KEY` | GitHub Models API key (for Stage 2 — Entity Extraction) |
| `ANTHROPIC_API_KEY` | Anthropic API key (available for future integrations) |

---

## Project Structure

```
Live_Trackers/
├── streamlit_app.py           # Streamlit dashboard
├── .streamlit/config.toml     # Streamlit theme and server config
├── tracker_config.json        # Node definitions, search queries, classification labels
├── node_tracker.py            # Stage 1: Perplexity node status monitoring
├── entity_extractor.py        # Stage 2: Llama Scout entity extraction
├── convergence_detector.py    # Stage 3: Multi-node convergence detection
├── run_pipeline.sh            # Full pipeline runner
├── requirements.txt           # Python dependencies (includes Streamlit)
├── SETUP.md                   # GitHub Actions setup guide
├── .github/workflows/
│   ├── deploy.yml             # CI/CD: validate on push to main
│   └── run_pipeline.yml       # Scheduled pipeline execution
├── _AI_CONTEXT_INDEX/         # Synced from The Regulated Friction Project
├── output/                    # Pipeline outputs (gitignored)
│   ├── node_status.json
│   ├── extracted_entities.json
│   ├── convergence_report.json
│   └── history/               # Timestamped run history
├── .env                       # API keys (gitignored)
└── .gitignore
```

---

## Connection to The Regulated Friction Project

This repository is the operational monitoring layer for the analytical framework documented in [The Regulated Friction Project](https://github.com/Leerrooy95/The_Regulated_Friction_Project). The `_AI_CONTEXT_INDEX/` directory is synced from the parent project via GitHub Actions and provides the knowledge base context.

**Key framework reference:**
- Core correlation: r = +0.6196 (p = 0.0004) between friction and compliance events
- Convergence window: 7-day median lag
- Active leverage nodes: documented in `09_CURRENT_THREADS.md`
- Capital architecture: documented in `04_CAPITAL_ARCHITECTURE.md`

---

## API Budget

The pipeline includes a daily API budget tracker (`.api_budget.json`) to prevent runaway costs:
- **Perplexity:** 50 calls/day default (configurable in `node_tracker.py`)
- **Llama Scout:** 1 call per pipeline run (extracts from all nodes at once)
- **Convergence detection:** No API calls (local analysis only)

---

*First line of Python: October 2025. Everything above: built since then.*
