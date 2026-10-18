import os
import time

import requests
from flask import Flask, jsonify, request, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)

KB = '''You are the assistant for Skill Filled Academia (Hunar & Hikmah), F-7 Markaz, Islamabad.
Answer only from these facts. Keep replies short. Reply in the user's language (English or Roman Urdu).
If you are not sure, tell them to message WhatsApp +92 302 8117726. Never invent fees, dates or promises.

Digital Skills Academy: 9 courses, 6 months each, 6,900 PKR or 30 USD per month. Mon-Thu, 1 hour per session, 10-20 students per batch. Live online and onsite.
Courses: Digital Marketing, Graphic Designing, Web Development, Video Editing & Animation, UI/UX Designing, E-Commerce Management, IT Fundamentals & Digital Literacy, Freelancing, AI & Automation.
Quran program for children aged 5-12: 6,900 PKR per month, 30 min sessions, Mon-Fri, 18 months (Noorani Qaida, Quran reading, Quran completion, Islamic studies throughout).
Other departments: Center for Personal Development (6 courses), Analytics & Business Intelligence (1), Islamic Studies & Languages (6). Details and fees via WhatsApp.
Careers: sales agents, instructors, admin and support. Email skillfilledacademia@gmail.com.
Contact: WhatsApp +92 302 8117726, email skillfilledacademia@gmail.com.'''

hits = {}  # ip -> request times in the last minute


def too_many(ip):
    now = time.time()
    recent = [t for t in hits.get(ip, []) if now - t < 60]
    recent.append(now)
    hits[ip] = recent
    return len(recent) > 15


def check(r):
    # show the API's own error text in the logs
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")


def ask_gemini(msgs):
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": KB}]},
        "contents": [
            {"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]}
            for m in msgs
        ],
        "generationConfig": {"maxOutputTokens": 600},
    }
    level = os.getenv("GEMINI_THINKING", "low")  # 3.8 Flash has no "minimal"
    if level:
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": level}
    r = requests.post(url, json=body, timeout=25,
                      headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    check(r)
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def ask_groq(msgs):
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    body = {
        "model": model,
        "messages": [{"role": "system", "content": KB}] + msgs,
        "max_completion_tokens": 500,
    }
    if "gpt-oss" in model:
        body["reasoning_effort"] = "low"  # keep replies fast
    r = requests.post("https://api.groq.com/openai/v1/chat/completions", json=body, timeout=25,
                      headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"]})
    check(r)
    return r.json()["choices"][0]["message"]["content"]


@app.route("/")
def home():
    return send_from_directory(BASE, "index.html")


@app.route("/health")
def health():
    return "ok"


@app.route("/assets/<path:name>")
def assets(name):
    return send_from_directory(os.path.join(BASE, "assets"), name)


@app.route("/api/chat", methods=["POST"])
def chat():
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
    if too_many(ip):
        return jsonify(error="slow down"), 429

    data = request.get_json(silent=True) or {}
    raw = data.get("messages")
    if not isinstance(raw, list):
        return jsonify(error="bad input"), 400
    msgs = [
        {"role": "user" if m.get("role") == "user" else "assistant",
         "content": str(m.get("content", ""))[:500]}
        for m in raw[-6:] if isinstance(m, dict)
    ]
    if not msgs or msgs[-1]["role"] != "user":
        return jsonify(error="bad input"), 400

    # try Gemini first, then Groq
    for name, fn in (("gemini", ask_gemini), ("groq", ask_groq)):
        try:
            reply = fn(msgs)
            if reply:
                return jsonify(reply=reply.strip(), via=name)
        except Exception as e:
            print(name, "failed:", e)
    return jsonify(error="unavailable"), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
