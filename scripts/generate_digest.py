"""
Generate a Markdown knowledge-base digest from verified live data.

Reads the JSON output files synced from the Live_Trackers pipeline and
produces a single Markdown file at
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


def _resolve(filename: str) -> dict | list | None:
    """Try output/ subdirectory first, then top level."""
    data = load_json(LIVE_DATA_DIR / "output" / filename)
    if data is None:
        data = load_json(LIVE_DATA_DIR / filename)
    return data


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


def format_node_status(data: dict) -> str:
    """Format node_status.json into a digest section."""
    lines = []
    nodes = data.get("nodes", data.get("node_statuses", data.get("results", {})))
    if isinstance(nodes, list):
        for node in nodes:
            name = node.get("node", node.get("name", "N/A"))
            status = node.get("status", "unknown")
            summary = node.get("summary", "")
            lines.append(f"- **{name}** — `{status}`")
            if summary:
                lines.append(f"  - {summary}")
    elif isinstance(nodes, dict):
        for name, info in nodes.items():
            status = info.get("status", "unknown") if isinstance(info, dict) else info
            summary = info.get("summary", "") if isinstance(info, dict) else ""
            lines.append(f"- **{name}** — `{status}`")
            if summary:
                lines.append(f"  - {summary}")
    gen = data.get("generated_at", data.get("run_timestamp", ""))
    if gen:
        lines.append(f"\n*Node scan: {gen}*")
    return "\n".join(lines)


def format_convergence(data: dict) -> str:
    """Format convergence_report.json into a digest section."""
    lines = []
    score = data.get("convergence_score", data.get("score", ""))
    if score:
        lines.append(f"- **Convergence score:** {score}")
    level = data.get("alert_level", data.get("level", ""))
    if level:
        lines.append(f"- **Alert level:** {level}")
    clusters = data.get("clusters", data.get("convergence_clusters", []))
    if isinstance(clusters, list):
        for cl in clusters:
            if isinstance(cl, dict):
                label = cl.get("label", cl.get("name", "Cluster"))
                nodes = cl.get("nodes", cl.get("members", []))
                lines.append(f"- **{label}:** {', '.join(str(n) for n in nodes)}")
            else:
                lines.append(f"- {cl}")
    events = data.get("convergence_events", [])
    if isinstance(events, list) and events:
        lines.append(f"- **Convergence events detected:** {len(events)}")
        for ev in events[:3]:
            if isinstance(ev, dict):
                date = ev.get("date", "")
                count = ev.get("active_node_count", "")
                if date and count:
                    lines.append(f"  - {date}: {count} active nodes")
    gen = data.get("generated_at", data.get("analysis_timestamp", ""))
    if gen:
        lines.append(f"\n*Convergence analysis: {gen}*")
    return "\n".join(lines)


def format_fact_check(data: dict) -> str:
    """Format fact_check.json into a digest section."""
    lines = []
    results = data.get("results", data.get("corrections_applied", data.get("checks", [])))
    if isinstance(results, list):
        for item in results:
            claim = item.get("claim", item.get("corrected_headline", item.get("statement", "N/A")))
            verdict = item.get("verdict", item.get("result", item.get("finding", "")))
            confidence = item.get("confidence", "")
            lines.append(f"- **{verdict}** — {claim}")
            if confidence:
                lines.append(f"  - Confidence: {confidence}")
    gen = data.get("generated_at", data.get("checked_at", ""))
    if gen:
        lines.append(f"\n*Fact-check run: {gen}*")
    return "\n".join(lines)


def format_entities(data: dict) -> str:
    """Format extracted_entities.json into a digest section."""
    lines = []
    entities = data.get("entities", data.get("results", []))
    if isinstance(entities, list):
        names = []
        for ent in entities:
            if isinstance(ent, dict):
                names.append(ent.get("name", ent.get("entity", str(ent))))
            else:
                names.append(str(ent))
        if names:
            lines.append(", ".join(names))
    elif isinstance(entities, dict):
        for category, items in entities.items():
            if isinstance(items, list):
                lines.append(f"**{category}:** {', '.join(str(i) for i in items)}")
    gen = data.get("generated_at", "")
    if gen:
        lines.append(f"\n*Entity extraction: {gen}*")
    return "\n".join(lines)


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Use explicit None checks rather than truthiness to avoid skipping empty dicts.
    daily = _resolve("daily_intelligence.json")
    verification = _resolve("live_verification.json")
    node_status = _resolve("node_status.json")
    convergence = _resolve("convergence_report.json")
    fact_check = _resolve("fact_check.json")
    entities = _resolve("extracted_entities.json")

    if all(d is None for d in [daily, verification, node_status, convergence, fact_check, entities]):
        print("No live data files found — skipping digest generation.")
        return 0

    sections = []
    sections.append("# 📡 Live Intelligence Digest")
    sections.append("")
    sections.append(f"> **Auto-generated:** {now}")
    sections.append("> **Source:** Synced twice daily from the Live_Trackers pipeline")
    sections.append("> **Purpose:** Provides the chatbot with the latest verified intelligence data.")
    sections.append("> This file is separate from the core _AI_CONTEXT_INDEX files and is regenerated each sync cycle.")
    sections.append("")

    if daily and isinstance(daily, dict):
        gen_at = daily.get("generated_at", "unknown")
        gen_by = daily.get("generated_by", "unknown")
        sections.append("## Data Timestamp")
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

        daily_entities = daily.get("entities_scanned", [])
        if daily_entities:
            sections.append("## Entities Scanned")
            if isinstance(daily_entities, list):
                sections.append(", ".join(daily_entities))
            else:
                sections.append(str(daily_entities))
            sections.append("")

    # Node Status (from node_tracker.py)
    if node_status and isinstance(node_status, dict):
        text = format_node_status(node_status)
        if text.strip():
            sections.append("## Node Status")
            sections.append(text)
            sections.append("")

    # Convergence Detection (from convergence_detector.py)
    if convergence and isinstance(convergence, dict):
        text = format_convergence(convergence)
        if text.strip():
            sections.append("## Convergence Report")
            sections.append(text)
            sections.append("")

    # Extracted Entities (from entity_extractor.py)
    if entities and isinstance(entities, dict):
        text = format_entities(entities)
        if text.strip():
            sections.append("## Extracted Entities")
            sections.append(text)
            sections.append("")

    # Fact Check (from fact_checker.py)
    if fact_check and isinstance(fact_check, dict):
        text = format_fact_check(fact_check)
        if text.strip():
            sections.append("## Fact Check Results")
            sections.append(text)
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
