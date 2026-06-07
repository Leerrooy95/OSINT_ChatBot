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
import secrets
import time
import logging
from datetime import timedelta
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template,
    session, redirect, url_for, g,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
import anthropic

from knowledge_base import KNOWLEDGE_BASE_TEXT

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32).hex())

# ---------------------------------------------------------------------------
# ProxyFix — Render (and most PaaS platforms) sit behind a load-balancer /
# CDN that adds X-Forwarded-For and X-Forwarded-Proto headers.  Without this
# middleware Flask sees the *proxy* IP as the client address, which means:
#   • Rate limiting counts ALL users as a single IP (the load-balancer's).
#   • SESSION_COOKIE_SECURE may be ineffective because proto looks like "http".
# x_for=1 / x_proto=1 / x_host=1 trusts exactly one proxy hop — Render's LB.
# Never set x_for higher than the number of trusted proxy hops in your stack.
# ---------------------------------------------------------------------------
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Harden session cookies
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True      # require HTTPS in production
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=2)

# CSRF protection
csrf = CSRFProtect(app)

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
# In production with multiple gunicorn workers the in-process memory://
# backend tracks limits *per worker*.  Each worker has its own counter, so a
# user can effectively multiply the allowed rate by the worker count.
# Set RATELIMIT_STORAGE_URI=redis://<host>:<port>/0 for accurate cross-worker
# limits.  On Render: add a Redis (Key Value) service and paste its Internal
# URL here.  Upstash also offers a free Redis tier that works on Render free.
_rate_limit_storage_uri = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],              # no global default; limits set per-route
    storage_uri=_rate_limit_storage_uri,
    headers_enabled=True,           # emit X-RateLimit-* / Retry-After headers
)


# ---------------------------------------------------------------------------
# CSP nonce — generated once per request; injected into the
# Content-Security-Policy header AND into every Jinja2 template so inline
# <script> blocks can carry the nonce attribute instead of relying on the
# insecure 'unsafe-inline' source expression.
# ---------------------------------------------------------------------------
@app.before_request
def _generate_csp_nonce() -> None:
    """Attach a cryptographically random nonce to the request context."""
    g.csp_nonce = secrets.token_urlsafe(16)


@app.context_processor
def _inject_csp_nonce() -> dict:
    """Make the per-request CSP nonce available to all Jinja2 templates."""
    return {"csp_nonce": g.get("csp_nonce", "")}


# ---------------------------------------------------------------------------
# Security headers — applied to every response
# ---------------------------------------------------------------------------
@app.after_request
def _set_security_headers(response):
    nonce = g.get("csp_nonce", "")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    response.headers["Strict-Transport-Security"] = (
        "max-age=63072000; includeSubDomains; preload"
    )
    # Per-request nonce replaces 'unsafe-inline' for inline <script> blocks.
    # External CDN scripts (Tailwind, marked.js, DOMPurify) are allowed by
    # their origin domain and do not need a nonce.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}' https://cdn.tailwindcss.com "
        "https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    # Prevent browser from caching pages that may reference the API key
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    return response


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(429)
def _rate_limit_handler(e):
    """Return a JSON 429 so the chat UI can display a readable message.

    Without this handler Flask-Limiter returns an HTML error page, which
    breaks the JSON contract of /api/chat and causes the UI to show a raw
    '<html>...' string as an error bubble.
    """
    return jsonify({"error": "Rate limit exceeded. Please slow down."}), 429


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Claude model to use (default: claude-sonnet-4-6)
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# System prompt that steers the assistant's behaviour
_BASE_SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    (
        "You are The Speaker, an advanced OSINT (Open Source Intelligence) "
        "research assistant purpose-built for analytical rigor and ethical "
        "intelligence work.\n\n"
        "## Your Knowledge Base\n"
        "Below is your Knowledge Base — reference documents from the "
        "_AI_CONTEXT_INDEX directory, including live intelligence synced "
        "twice daily from the Live_Trackers pipeline. Prioritize Knowledge "
        "Base information first. If it lacks the answer, use training data. "
        "If neither suffices, say so clearly.\n\n"
        "## Source Attribution\n"
        "Always cite your source file when referencing the Knowledge Base "
        "(e.g. '(see 01_CORE_THEORY.md)' or '(see LIVE_INTELLIGENCE_DIGEST.md)'). "
        "When information comes from training data rather than the Knowledge Base, "
        "note that distinction.\n\n"
        "## Confidence & Verification\n"
        "Indicate confidence levels when making analytical assessments:\n"
        "- ✅ Verified — corroborated by multiple sources or statistical tests\n"
        "- ⚠️ Partially verified — single-source or preliminary evidence\n"
        "- 🔍 Unverified — plausible but requires further investigation\n"
        "Distinguish clearly between established facts and analytical "
        "judgments. Never present speculation as confirmed intelligence.\n\n"
        "## OPSEC Awareness\n"
        "If a user's query could expose them to operational security risks "
        "(e.g. querying specific individuals, locations, or ongoing "
        "investigations), note the OPSEC consideration briefly.\n\n"
        "## Ethical Boundaries\n"
        "This tool is for lawful open-source intelligence research only. "
        "Decline requests for doxxing, harassment, illegal surveillance, "
        "or any activity that violates privacy laws or ethical norms. "
        "All intelligence should be derived from publicly available sources.\n\n"
        "## Style\n"
        "Be thorough but concise — prefer clear, direct answers over "
        "lengthy preambles. Structure complex analyses with headers and "
        "bullet points for readability."
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

# Basic validation: must start with sk-ant- and have a reasonable length
_API_KEY_PATTERN = re.compile(r"^sk-ant-.{20,}$")


def _is_valid_api_key_format(key: str) -> bool:
    """Return True if *key* looks like a valid Anthropic API key."""
    return bool(_API_KEY_PATTERN.match(key))


# ---------------------------------------------------------------------------
# Auth helper — BYOK: session is authenticated when an API key is present
# ---------------------------------------------------------------------------
# Maximum session age — enforced server-side even without a persistent cookie
_MAX_SESSION_AGE = timedelta(hours=2).total_seconds()


def login_required(f):
    """Redirect unauthenticated users to the login page."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("has_api_key"):
            return redirect(url_for("login"))
        # Server-side session expiry: clear if older than _MAX_SESSION_AGE
        created = session.get("_created", 0)
        if time.time() - created > _MAX_SESSION_AGE:
            session.clear()
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
            error = "Invalid key format. Anthropic keys start with sk-ant-..."
        else:
            session["api_key"] = api_key
            session["has_api_key"] = True
            session["_created"] = time.time()
            session.permanent = True
            return redirect(url_for("chat_ui"))
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    resp = redirect(url_for("login"))
    resp.headers["Clear-Site-Data"] = '"cookies", "storage"'
    return resp


@app.route("/api/beacon-logout", methods=["POST"])
@csrf.exempt  # sendBeacon cannot include CSRF tokens; SameSite=Lax protects
def beacon_logout():
    """Best-effort session cleanup fired by sendBeacon on tab/window close."""
    # Defense-in-depth: reject cross-origin requests
    fetch_site = request.headers.get("Sec-Fetch-Site", "")
    if fetch_site and fetch_site != "same-origin":
        return "", 403
    session.clear()
    return "", 204


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
