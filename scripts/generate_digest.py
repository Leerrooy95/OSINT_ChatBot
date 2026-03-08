"""
Generate a Markdown knowledge-base digest from verified live data.

Reads the daily_intelligence.json and live_verification.json files from
the _LIVE_DATA/ directory and produces a single Markdown file at
_AI_CONTEXT_INDEX/LIVE_INTELLIGENCE_DIGEST.md that the knowledge-base
loader picks up automatically via rglob("*.md").

This script is called by the sync_live_data workflow after validation.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LIVE_DATA_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("_LIVE_DATA")
OUTPUT_DIR = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("_AI_CONTEXT_INDEX")


def load_json(path: Path) -> dict | list | None:
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def format_developments(items: list[dict]) -> str:
    lines = []
    for i, item in enumerate(items, 1):
        headline = item.get("headline", "N/A")
        summary = item.get("summary", "")
        event_type = item.get("event_type", "")
        source = item.get("source", "")
        lines.append(f"### {i}. {headline}")
        if event_type:
            lines.append(f"**Type:** {event_type}")
        if summary:
            lines.append(f"\n{summary}")
        if source:
            lines.append(f"\n*Source: {source}*")
        lines.append("")
    return "\n".join(lines)


def format_alerts(items: list[dict]) -> str:
    lines = []
    for item in items:
        headline = item.get("headline", "N/A")
        priority = item.get("priority", "")
        relevance = item.get("relevance", "")
        lines.append(f"- **[{priority}]** {headline}")
        if relevance:
            lines.append(f"  - {relevance}")
    return "\n".join(lines)


def format_watchlist(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def format_signals(items: list[dict]) -> str:
    lines = []
    for item in items:
        status = item.get("status", "")
        headline = item.get("headline", "N/A")
        event_type = item.get("event_type", "")
        lines.append(f"- **[{status}]** ({event_type}) {headline}")
    return "\n".join(lines)


def format_verification(results: list[dict]) -> str:
    lines = []
    for item in results:
        prediction = item.get("prediction", "N/A")
        status = item.get("status", "")
        description = item.get("description", "")
        timeframe = item.get("timeframe", "")
        lines.append(f"### {prediction}")
        lines.append(f"**Status:** {status} | **Timeframe:** {timeframe}")
        if description:
            lines.append(f"\n{description}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Files may be at top level or in output/ subdirectory depending on source
    daily = (
        load_json(LIVE_DATA_DIR / "output" / "daily_intelligence.json")
        or load_json(LIVE_DATA_DIR / "daily_intelligence.json")
    )
    verification = (
        load_json(LIVE_DATA_DIR / "output" / "live_verification.json")
        or load_json(LIVE_DATA_DIR / "live_verification.json")
    )

    if not daily and not verification:
        print("No live data files found — skipping digest generation.")
        return 0

    sections = []
    sections.append("# 📡 Live Intelligence Digest")
    sections.append("")
    sections.append(f"> **Auto-generated:** {now}")
    sections.append("> **Source:** Synced daily from The_Regulated_Friction_Project")
    sections.append("> **Purpose:** Provides the chatbot with the latest verified intelligence data.")
    sections.append("> This file is separate from the core _AI_CONTEXT_INDEX files and is regenerated daily.")
    sections.append("")

    if daily and isinstance(daily, dict):
        gen_at = daily.get("generated_at", "unknown")
        gen_by = daily.get("generated_by", "unknown")
        sections.append(f"## Data Timestamp")
        sections.append(f"- **Generated:** {gen_at}")
        sections.append(f"- **Source engine:** {gen_by}")
        sections.append("")

        top3 = daily.get("top_3_developments", [])
        if top3:
            sections.append("## Top Developments")
            sections.append(format_developments(top3))

        alerts = daily.get("new_alerts", [])
        if alerts:
            sections.append("## New Alerts")
            sections.append(format_alerts(alerts))
            sections.append("")

        signals = daily.get("signal_updates", [])
        if signals:
            sections.append("## Active Signals")
            sections.append(format_signals(signals))
            sections.append("")

        watchlist = daily.get("priority_watchlist", [])
        if watchlist:
            sections.append("## Priority Watchlist")
            sections.append(format_watchlist(watchlist))
            sections.append("")

        entities = daily.get("entities_scanned", [])
        if entities:
            sections.append("## Entities Scanned")
            sections.append(", ".join(entities))
            sections.append("")

    if verification and isinstance(verification, dict):
        status_summary = verification.get("status_summary", {})
        results = verification.get("results", [])
        total = verification.get("total_predictions", 0)

        sections.append("## Live Verification Summary")
        sections.append(f"- **Total predictions tracked:** {total}")
        for key, val in status_summary.items():
            sections.append(f"- **{key.capitalize()}:** {val}")
        sections.append("")

        if results:
            sections.append("## Prediction Tracker")
            sections.append(format_verification(results))

    sections.append("---")
    sections.append(f"*Digest generated {now} by sync_live_data workflow.*")

    digest_text = "\n".join(sections)

    output_path = OUTPUT_DIR / "LIVE_INTELLIGENCE_DIGEST.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(digest_text)

    print(f"✅ Digest written: {output_path} ({len(digest_text):,} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
