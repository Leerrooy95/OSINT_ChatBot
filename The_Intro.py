import os
import json
from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
from functools import wraps
from openai import OpenAI

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(32).hex())

# --- CONFIGURATION ---
# The master password to unlock the chat (Defaults to 'trident2026')
APP_PASSWORD = os.environ.get("APP_PASSWORD", "trident2026")

# Your DigitalOcean Agent details
# Base URL must end with /api/v1 for the OpenAI SDK to work with DO Agents
# Using the URL from your screenshot as the default
DO_AGENT_ENDPOINT = os.environ.get(
    "DO_AGENT_ENDPOINT", 
    "https://lqne5ltx5k46s4mhpxf7h2ly.agents.do-ai.run/api/v1"
)
DO_AGENT_KEY = os.environ.get("DO_AGENT_KEY", "")

# --- HTML TEMPLATES ---
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The Speaker - Secure Login</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-900 flex items-center justify-center h-screen text-slate-200">
    <div class="bg-slate-800 p-8 rounded-xl shadow-2xl w-96 max-w-full border border-slate-700">
        <div class="text-center mb-6">
            <h1 class="text-3xl font-bold text-emerald-400 mb-2">🔱 Trident</h1>
            <p class="text-sm text-slate-400">OSINT Knowledge Base Access</p>
        </div>
        {% if error %}
            <div class="mb-4 text-sm text-red-400 bg-red-900/30 p-3 rounded border border-red-800">{{ error }}</div>
        {% endif %}
        <form action="/login" method="post" class="space-y-4">
            <div>
                <label class="block text-sm font-semibold text-slate-300 mb-1">Clearance Code</label>
                <input type="password" name="password" required autofocus
                    class="w-full px-4 py-2 bg-slate-900 border border-slate-600 rounded-md focus:ring-2 focus:ring-emerald-500 text-white outline-none transition">
            </div>
            <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-2 rounded-md transition duration-200 shadow-md">
                Authenticate
            </button>
        </form>
    </div>
</body>
</html>
"""

CHAT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>The Speaker | Trident OSINT</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        /* Custom scrollbar for a sleek look */
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #475569; }
        
        .typing-indicator span {
            display: inline-block;
            width: 6px; height: 6px;
            background-color: #10b981;
            border-radius: 50%;
            animation: typing 1s infinite alternate;
            margin: 0 2px;
        }
        .typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
        .typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes typing {
            0% { transform: translateY(0); opacity: 0.5; }
            100% { transform: translateY(-4px); opacity: 1; }
        }
    </style>
</head>
<body class="bg-slate-900 text-slate-200 font-sans h-screen flex flex-col overflow-hidden">
    
    <!-- Header -->
    <header class="bg-slate-950 border-b border-slate-800 px-6 py-4 flex justify-between items-center shrink-0 shadow-md z-10">
        <div class="flex items-center space-x-3">
            <span class="text-2xl">🔱</span>
            <div>
                <h1 class="text-lg font-bold text-white leading-tight">The_Speaker</h1>
                <p class="text-xs text-emerald-400 font-mono">Opus 4.6 • friction-intel-kb connected</p>
            </div>
        </div>
        <a href="/logout" class="text-sm text-slate-400 hover:text-white transition px-3 py-1 rounded hover:bg-slate-800">Disconnect</a>
    </header>

    <!-- Chat Area -->
    <div id="chat-container" class="flex-1 overflow-y-auto p-4 md:p-6 space-y-6 scroll-smooth pb-32">
        <!-- Initial Greeting -->
        <div class="flex justify-start">
            <div class="max-w-[85%] md:max-w-[75%] bg-slate-800 border border-slate-700 rounded-2xl rounded-tl-sm p-4 shadow-sm text-sm md:text-base leading-relaxed">
                <p>System online. OSINT Investigator profile active. I am monitoring the Regulated Friction Knowledge Base and live search metrics.</p>
                <p class="mt-2 text-slate-400 text-xs font-mono">Awaiting your query...</p>
            </div>
        </div>
    </div>

    <!-- Input Area -->
    <div class="bg-slate-950 border-t border-slate-800 p-4 shrink-0 absolute bottom-0 w-full z-10 shadow-[0_-10px_15px_-3px_rgba(0,0,0,0.3)]">
        <div class="max-w-4xl mx-auto relative flex items-end">
            <textarea id="user-input" rows="1" 
                class="w-full bg-slate-800 border border-slate-600 text-white rounded-xl pl-4 pr-14 py-3 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent resize-none overflow-hidden transition-all"
                placeholder="Ask The Speaker about recent friction events..."></textarea>
            <button id="send-btn" class="absolute right-2 bottom-2 p-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z" />
                </svg>
            </button>
        </div>
    </div>

    <script>
        const inputField = document.getElementById('user-input');
        const sendBtn = document.getElementById('send-btn');
        const chatContainer = document.getElementById('chat-container');
        
        // Client-side memory of the conversation
        let conversationHistory = [];

        // Auto-resize textarea
        inputField.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight < 120 ? this.scrollHeight : 120) + 'px';
            if(this.value.trim() === '') this.style.height = 'auto';
        });

        // Handle Enter key (Shift+Enter for new line)
        inputField.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        sendBtn.addEventListener('click', sendMessage);

        function appendMessage(role, content) {
            const isUser = role === 'user';
            const wrapper = document.createElement('div');
            wrapper.className = `flex ${isUser ? 'justify-end' : 'justify-start'}`;
            
            // Basic markdown-to-html for line breaks
            const formattedContent = content.replace(/\\n/g, '<br>');

            wrapper.innerHTML = `
                <div class="max-w-[85%] md:max-w-[75%] ${isUser ? 'bg-emerald-700 text-white rounded-tr-sm' : 'bg-slate-800 border border-slate-700 text-slate-200 rounded-tl-sm'} rounded-2xl p-4 shadow-sm text-sm md:text-base leading-relaxed">
                    ${formattedContent}
                </div>
            `;
            chatContainer.appendChild(wrapper);
            window.scrollTo(0, document.body.scrollHeight);
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }

        function showTypingIndicator() {
            const wrapper = document.createElement('div');
            wrapper.id = 'typing-indicator';
            wrapper.className = 'flex justify-start mb-4';
            wrapper.innerHTML = `
                <div class="bg-slate-800 border border-slate-700 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
                    <div class="typing-indicator flex items-center h-4">
                        <span></span><span></span><span></span>
                    </div>
                </div>
            `;
            chatContainer.appendChild(wrapper);
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }

        function removeTypingIndicator() {
            const indicator = document.getElementById('typing-indicator');
            if (indicator) indicator.remove();
        }

        async function sendMessage() {
            const text = inputField.value.trim();
            if (!text) return;

            // 1. Display user message
            inputField.value = '';
            inputField.style.height = 'auto';
            appendMessage('user', text);
            conversationHistory.push({ role: 'user', content: text });

            // 2. Lock input and show typing
            inputField.disabled = true;
            sendBtn.disabled = true;
            showTypingIndicator();

            try {
                // 3. Send history to Flask backend
                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ messages: conversationHistory })
                });

                const data = await response.json();
                removeTypingIndicator();

                if (response.ok) {
                    // 4. Display AI response
                    appendMessage('assistant', data.reply);
                    conversationHistory.push({ role: 'assistant', content: data.reply });
                } else {
                    appendMessage('assistant', `⚠️ System Error: ${data.error}`);
                }
            } catch (err) {
                removeTypingIndicator();
                appendMessage('assistant', '⚠️ Connection lost. Unable to reach the server.');
            } finally {
                inputField.disabled = false;
                sendBtn.disabled = false;
                inputField.focus();
            }
        }
    </script>
</body>
</html>
"""

# --- AUTH DECORATOR ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# --- ROUTES ---
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("chat_ui"))
        else:
            error = "Invalid clearance code."
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def chat_ui():
    return render_template_string(CHAT_HTML)

@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    """
    Secure backend route. Receives the chat history from the browser,
    sends it to DigitalOcean's OpenAI-compatible endpoint, and returns the reply.
    This ensures DO_AGENT_KEY is never exposed to the browser.
    """
    data = request.json
    messages = data.get("messages", [])

    if not messages:
        return jsonify({"error": "No messages provided"}), 400

    if not DO_AGENT_KEY:
        return jsonify({"error": "DO_AGENT_KEY is not configured on the server."}), 500

    try:
        # Initialize the client pointed at your DigitalOcean Agent
        client = OpenAI(
            base_url=DO_AGENT_ENDPOINT,
            api_key=DO_AGENT_KEY
        )

        # DO Agents use the 'model' parameter generically.
        # The specific model (Opus 4.6) is configured in your DO Dashboard.
        response = client.chat.completions.create(
            model="agent", 
            messages=messages,
            # Adjust max_tokens if you expect massive geopolitical essays
            max_tokens=4096 
        )

        reply_text = response.choices[0].message.content
        return jsonify({"reply": reply_text})

    except Exception as e:
        print(f"Backend API Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Runs the app locally
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
