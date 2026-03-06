"""
The Speaker — Personal OSINT Chatbot

A Flask web application that proxies chat messages to Claude via the
Anthropic Messages API. The assistant has web-search guidance built into
its system prompt so it will:
  1. Use its training data and reasoning
  2. Cite sources when drawing on web search results

All configuration is done through environment variables so the app can be
deployed on Render (or any host) without touching the source code.
"""

import os
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template,
    session, redirect, url_for,
)
import anthropic

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32).hex())

# Harden session cookies
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ---------------------------------------------------------------------------
# Configuration — all from environment variables
# ---------------------------------------------------------------------------
APP_PASSWORD = os.environ.get("APP_PASSWORD", "trident2026")

# Anthropic API key
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Claude model to use (default: claude-sonnet-4-6)
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# System prompt that steers the assistant's behaviour
SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    (
        "You are The Speaker, an advanced OSINT research assistant. "
        "When answering questions, always prioritize information from your "
        "attached Knowledge Base files first. If the Knowledge Base does not "
        "contain the answer, use your training data. If neither source is "
        "sufficient, perform a live web search to find the most accurate and "
        "up-to-date information. Always cite your sources when using web "
        "search results."
    ),
)


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
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
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


@app.route("/api/chat", methods=["POST"])
@login_required
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
