"""
Knowledge Base loader for The Speaker.

Reads every Markdown file inside the _AI_CONTEXT_INDEX/ directory tree once at
import time and exposes the combined text as `KNOWLEDGE_BASE_TEXT`.  The result
is cached so subsequent imports are essentially free.

The files are sorted to guarantee a deterministic load order:
  1. 00_START_HERE.md and CONTEXT_ROUTER.md are placed first (navigation aids)
  2. Remaining top-level files in alphanumeric order
  3. Subdirectory files (Node_Dossiers/, sources/) in alphanumeric order
"""

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# Resolve the knowledge-base directory relative to *this* file so it works
# regardless of the working directory (local dev, gunicorn, etc.).
_KB_DIR = Path(__file__).resolve().parent / "_AI_CONTEXT_INDEX"


def _load_knowledge_base() -> str:
    """Return the concatenated content of every .md file in _AI_CONTEXT_INDEX/."""
    if not _KB_DIR.is_dir():
        log.warning("Knowledge base directory not found: %s", _KB_DIR)
        return ""

    md_files = sorted(_KB_DIR.rglob("*.md"))
    if not md_files:
        return ""

    # Prioritize navigation files so the model sees them first.
    priority = ("00_START_HERE.md", "CONTEXT_ROUTER.md")

    def _sort_key(p: Path) -> tuple:
        name = p.name
        try:
            idx = priority.index(name)
        except ValueError:
            idx = len(priority)
        return (idx, str(p))

    md_files.sort(key=_sort_key)

    sections: list[str] = []
    for md_path in md_files:
        rel = md_path.relative_to(_KB_DIR)
        try:
            content = md_path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("Failed to read knowledge base file %s: %s", md_path, exc)
            continue
        sections.append(
            f"=== FILE: {rel} ===\n{content}"
        )

    return "\n\n".join(sections)


# Cached at import time — loaded once per process.
KNOWLEDGE_BASE_TEXT: str = _load_knowledge_base()
