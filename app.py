"""
The Speaker — Personal OSINT Chatbot

A Flask web application that proxies chat messages to a DigitalOcean AI Agent.
The agent has a Knowledge Base attached and web-search enabled so it will:
  1. Check its Knowledge Base first
  2. Fall back to its training data
  3. Use live web search when the answer isn't available in its files

All configuration is done through environment variables so the app can be
deployed on Render (or any host) without touching the source code.
"""

import os
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template,
    session, redirect, url_for,
)
from openai import OpenAI

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

# DigitalOcean Agent endpoint (must end with /api/v1)
DO_AGENT_ENDPOINT = os.environ.get("DO_AGENT_ENDPOINT", "")
DO_AGENT_KEY = os.environ.get("DO_AGENT_KEY", "")

# System prompt that reinforces the Knowledge-Base-first priority
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
    Receives conversation history from the browser, prepends a system prompt
    that prioritises the Knowledge Base, sends it to the DigitalOcean Agent
    via the OpenAI-compatible API, and returns the reply.
    The DO_AGENT_KEY is never exposed to the browser.
    """
    data = request.get_json(silent=True) or {}
    messages = data.get("messages", [])

    if not messages:
        return jsonify({"error": "No messages provided."}), 400

    if not DO_AGENT_ENDPOINT:
        return jsonify({"error": "DO_AGENT_ENDPOINT is not configured on the server."}), 500

    if not DO_AGENT_KEY:
        return jsonify({"error": "DO_AGENT_KEY is not configured on the server."}), 500

    try:
        client = OpenAI(
            base_url=DO_AGENT_ENDPOINT,
            api_key=DO_AGENT_KEY,
        )

        # Prepend system prompt to steer KB-first behaviour
        full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

        response = client.chat.completions.create(
            model="agent",
            messages=full_messages,
            max_tokens=4096,
        )

        reply_text = response.choices[0].message.content
        return jsonify({"reply": reply_text})

    except Exception as e:
        app.logger.error("Agent API error: %s", e)
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
