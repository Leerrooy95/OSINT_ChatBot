"""
The Speaker — OSINT ChatBot  (BYOK Edition)

A Flask web application that proxies chat messages to Claude via the
Anthropic Messages API.  Users supply their own Anthropic API key
(Bring Your Own Key) — the server never stores keys on disk.

At startup the app loads every Markdown file in the
``_AI_CONTEXT_INDEX/`` directory and injects them into the system
prompt so the assistant can reference the Knowledge Base when answering
questions.

All configuration is done through environment variables so the app can be
deployed on Render (or any host) without touching the source code.
"""

import os
import re
import logging
from datetime import timedelta
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template,
    session, redirect, url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
import anthropic

from knowledge_base import KNOWLEDGE_BASE_TEXT

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32).hex())

# Harden session cookies
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True      # require HTTPS in production
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=2)

# CSRF protection
csrf = CSRFProtect(app)

# Rate limiting — uses client IP by default, in-memory storage
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],              # no global default; limits set per-route
    storage_uri="memory://",
)


# ---------------------------------------------------------------------------
# Security headers — applied to every response
# ---------------------------------------------------------------------------
@app.after_request
def _set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    response.headers["Strict-Transport-Security"] = (
        "max-age=63072000; includeSubDomains; preload"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com "
        "https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    return response


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Claude model to use (default: claude-sonnet-4-6)
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# System prompt that steers the assistant's behaviour
_BASE_SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    (
        "You are The Speaker, an advanced OSINT research assistant. "
        "Below is your Knowledge Base — reference documents from "
        "the _AI_CONTEXT_INDEX directory. Prioritize Knowledge Base "
        "information first. If it lacks the answer, use training data. If "
        "neither suffices, say so. Cite your source file when applicable "
        "(e.g. '(see 01_CORE_THEORY.md)'). Be thorough but concise — "
        "prefer clear, direct answers over lengthy preambles."
    ),
)

# Build the full system prompt by appending the Knowledge Base content.
if KNOWLEDGE_BASE_TEXT:
    SYSTEM_PROMPT = (
        f"{_BASE_SYSTEM_PROMPT}\n\n"
        f"--- START OF KNOWLEDGE BASE ---\n\n"
        f"{KNOWLEDGE_BASE_TEXT}\n\n"
        f"--- END OF KNOWLEDGE BASE ---"
    )
else:
    SYSTEM_PROMPT = _BASE_SYSTEM_PROMPT

# Regex for validating Anthropic API key format
_API_KEY_PATTERN = re.compile(r"^sk-ant-[A-Za-z0-9_-]{20,}$")


def _is_valid_api_key_format(key: str) -> bool:
    """Return True if *key* looks like a valid Anthropic API key."""
    return bool(_API_KEY_PATTERN.match(key))


# ---------------------------------------------------------------------------
# Auth helper — BYOK: session is authenticated when an API key is present
# ---------------------------------------------------------------------------
def login_required(f):
    """Redirect unauthenticated users to the login page."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("has_api_key"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    error = None
    if request.method == "POST":
        api_key = (request.form.get("api_key") or "").strip()
        if not api_key:
            error = "Please enter your Anthropic API key."
        elif not _is_valid_api_key_format(api_key):
            error = "Invalid key format. Anthropic keys start with sk-ant-…"
        else:
            session.permanent = True
            session["api_key"] = api_key
            session["has_api_key"] = True
            return redirect(url_for("chat_ui"))
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def chat_ui():
    return render_template("chat.html")


MAX_CONVERSATION_MESSAGES = 50   # keep the last N messages to bound context size
MAX_MESSAGE_LENGTH = 20_000      # per-message character limit


@app.route("/api/chat", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
@csrf.exempt                       # JSON endpoint; session cookie is SameSite=Lax
def api_chat():
    """
    BYOK backend route.
    Receives conversation history from the browser, prepends a system prompt,
    sends it to Claude via the Anthropic Messages API using the user's own
    API key (stored in the encrypted session), and returns the reply.
    The API key is never logged or exposed.
    """
    data = request.get_json(silent=True) or {}
    messages = data.get("messages", [])

    if not messages:
        return jsonify({"error": "No messages provided."}), 400

    # Retrieve the user's API key from the encrypted session
    user_api_key = session.get("api_key", "")
    if not user_api_key:
        return jsonify({"error": "No API key found. Please log in again."}), 401

    # --- Input validation ---------------------------------------------------
    validated: list[dict] = []
    for msg in messages[-MAX_CONVERSATION_MESSAGES:]:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        validated.append({
            "role": role,
            "content": content[:MAX_MESSAGE_LENGTH],
        })

    if not validated:
        return jsonify({"error": "No valid messages provided."}), 400

    try:
        client = anthropic.Anthropic(api_key=user_api_key)

        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=16384,
            system=SYSTEM_PROMPT,
            messages=validated,
        )

        reply_text = response.content[0].text
        return jsonify({"reply": reply_text})

    except anthropic.AuthenticationError:
        log.warning("Anthropic authentication failed for a user session")
        session.clear()
        return jsonify({
            "error": "API key is invalid or expired. Please log in with a valid key."
        }), 401

    except anthropic.RateLimitError:
        log.warning("Anthropic rate limit reached")
        return jsonify({"error": "Rate limit reached. Please try again shortly."}), 429

    except anthropic.APIError as e:
        log.error("Anthropic API error: %s", e)
        return jsonify({"error": "The AI service returned an error. Please try again."}), 502

    except Exception as e:
        log.error("Unexpected error in /api/chat: %s", e)
        return jsonify({"error": "An internal error occurred. Please try again."}), 500


# ---------------------------------------------------------------------------
# Health-check endpoint (useful for Render zero-downtime deploys)
# ---------------------------------------------------------------------------
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# Local development entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    print(f"\n🔱  The Speaker — OSINT ChatBot running on http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
