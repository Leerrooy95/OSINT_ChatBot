"""
The Speaker — OSINT ChatBot

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
# Configuration — all from environment variables
# ---------------------------------------------------------------------------
APP_PASSWORD = os.environ.get("APP_PASSWORD")
if not APP_PASSWORD:
    sys.exit("FATAL: APP_PASSWORD environment variable is not set. Exiting.")

# Anthropic API key — validate format at startup
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
if ANTHROPIC_API_KEY and not ANTHROPIC_API_KEY.startswith("sk-ant-"):
    app.logger.warning("ANTHROPIC_API_KEY does not match expected format (sk-ant-...).")

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
        password = request.form.get("password")
        if password is not None and hmac.compare_digest(password, APP_PASSWORD):
            session.permanent = True
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
MAX_MESSAGE_LENGTH = 20_000      # per-message character limit


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
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=16384,
            system=SYSTEM_PROMPT,
            messages=validated,
        )

        reply_text = response.content[0].text
        return jsonify({"reply": reply_text})

    except anthropic.AuthenticationError:
        app.logger.error("Anthropic API authentication failed")
        return jsonify({"error": "API authentication failed. Check server configuration."}), 500

    except anthropic.RateLimitError:
        app.logger.error("Anthropic API rate limit reached")
        return jsonify({"error": "Rate limit reached. Please try again shortly."}), 429

    except anthropic.APIError as e:
        app.logger.error("Anthropic API error: %s", e)
        return jsonify({"error": "The AI service returned an error. Please try again."}), 502

    except Exception as e:
        app.logger.error("Unexpected error in /api/chat: %s", e)
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
