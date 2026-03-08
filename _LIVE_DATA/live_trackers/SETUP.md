# GitHub Actions Setup — Live Trackers

Everything runs through **GitHub Actions** — no external servers required.
The pipeline executes on GitHub-hosted runners, and results are committed
back to the `output/` folder automatically.

---

## 1. GitHub Secrets (Required)

In your GitHub repository, go to **Settings → Secrets and variables → Actions**
and add these **repository secrets**:

### Pipeline Secrets (required for `Run Tracker Pipeline`)

| Secret Name          | Value                                              |
|----------------------|----------------------------------------------------|
| `PERPLEXITY_API_KEY` | Your Perplexity API key                            |
| `LLAMA_SCOUT_KEY`    | Your GitHub Models API key (for Llama Scout)       |
| `ANTHROPIC_API_KEY`  | Your Anthropic API key (available for future use)  |

Once the secrets are set, the GitHub Actions workflows will:
- **Validate** on every push to `main` — linting, config checks, secret scanning
- **Run the pipeline** twice daily (08:00 and 20:00 UTC) — writing output to `output/`
- Both can also be triggered manually from the **Actions** tab

---

## 2. Local Development (Optional)

### Prerequisites

```bash
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file (never commit this):

```
PERPLEXITY_API_KEY=your_perplexity_api_key_here
LLAMA_SCOUT_KEY=your_github_models_api_key_here
```

Secure the file:

```bash
chmod 600 .env
```

### Running the Pipeline Locally

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

# Dry run (no API calls)
python node_tracker.py --dry-run
```

---

## 3. Streamlit Dashboard (Optional)

The project includes a Streamlit dashboard for visualizing tracker data:

```bash
streamlit run streamlit_app.py
```

> **Note:** By default Streamlit binds to `127.0.0.1` (see `.streamlit/config.toml`).

---

## 4. Workflows

### `deploy.yml` — Validate on Push

Triggered on every push to `main` (or manually). Runs:
- Python 3.12 setup and dependency install
- `tracker_config.json` validation
- Streamlit import check
- Pipeline script compilation check
- Hardcoded secret scan

### `run_pipeline.yml` — Scheduled Pipeline

Runs twice daily at **08:00 and 20:00 UTC** (or manually). Executes:
1. **Stage 1 — Node Tracker** (Perplexity sonar-pro)
2. **Stage 2 — Entity Extractor** (Llama Scout 17B) — continues on error
3. **Stage 3 — Convergence Detector** (local analysis) — continues on error
4. **Commit and push** output back to `main`

---

## 5. Security Checklist

- [x] GitHub secrets for API credentials (no keys in code)
- [x] No hardcoded API keys in source code (validated by CI)
- [x] `.env` file gitignored
- [x] Streamlit bound to `127.0.0.1` in config
- [x] XSRF protection enabled in Streamlit config
- [x] Usage stats collection disabled

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Pipeline fails with "PERPLEXITY_API_KEY not set" | Add `PERPLEXITY_API_KEY` secret in repo Settings → Secrets |
| Entity extraction fails | Add `LLAMA_SCOUT_KEY` secret (your GitHub Models API key) |
| Validation fails on push | Check the Actions tab for specific error messages |
| No output committed | Pipeline may have had no new data; check workflow logs |

---

*Live Trackers — The Regulated Friction Project*
