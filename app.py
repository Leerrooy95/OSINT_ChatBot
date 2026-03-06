"""
The Speaker — Personal OSINT Chatbot

A Flask web application that proxies chat messages to Claude via the
Anthropic Messages API.  At startup the app loads every Markdown file in
the ``_AI_CONTEXT_INDEX/`` directory and injects them into the system
prompt so the assistant can reference the Knowledge Base when answering
questions.

All configuration is done through environment variables so the app can be
deployed on Render (or any host) without touching the source code.
"""

import os
import hmac
import sys
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

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32).hex())

# Harden session cookies
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

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
# Configuration — all from environment variables
# ---------------------------------------------------------------------------
APP_PASSWORD = os.environ.get("APP_PASSWORD")
if not APP_PASSWORD:
    sys.exit("FATAL: APP_PASSWORD environment variable is not set. Exiting.")

# Anthropic API key
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Claude model to use (default: claude-sonnet-4-6)
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# System prompt that steers the assistant's behaviour
_BASE_SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    (
        "You are The Speaker, an advanced OSINT research assistant. "
        "Below is your Knowledge Base — a collection of reference documents "
        "loaded from the _AI_CONTEXT_INDEX directory. When answering "
        "questions, always prioritize information from this Knowledge Base "
        "first. If the Knowledge Base does not contain the answer, use your "
        "training data. If neither source is sufficient, say so clearly. "
        "Always cite which Knowledge Base file you are drawing from when "
        "applicable (e.g. '(see 01_CORE_THEORY.md)')."
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


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------
def login_required(f):
    """Redirect unauthenticated users to the login page."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
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
        if hmac.compare_digest(request.form.get("password", ""), APP_PASSWORD):
            session["logged_in"] = True
            return redirect(url_for("chat_ui"))
        else:
            error = "Invalid clearance code."
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


@app.route("/api/chat", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
@csrf.exempt                       # JSON endpoint; session cookie is SameSite=Lax
def api_chat():
    """
    Secure backend route.
    Receives conversation history from the browser, prepends a system prompt,
    sends it to Claude via the Anthropic Messages API, and returns the reply.
    The ANTHROPIC_API_KEY is never exposed to the browser.
    """
    data = request.get_json(silent=True) or {}
    messages = data.get("messages", [])

    if not messages:
        return jsonify({"error": "No messages provided."}), 400

    if not ANTHROPIC_API_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY is not configured on the server."}), 500

    # Truncate to the most recent messages to prevent unbounded context growth.
    messages = messages[-MAX_CONVERSATION_MESSAGES:]

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
        )

        reply_text = response.content[0].text
        return jsonify({"reply": reply_text})

    except Exception as e:
        app.logger.error("Anthropic API error: %s", e)
        return jsonify({"error": str(e)}), 500


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
    print(f"\n🔱  The Speaker — running on http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
