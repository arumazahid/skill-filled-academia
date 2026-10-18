const KB = `You are the assistant for Skill Filled Academia (Hunar & Hikmah), F-7 Markaz, Islamabad.
Answer only from these facts. Keep replies short. Reply in the user's language (English or Roman Urdu).
If you are not sure, tell them to message WhatsApp +92 302 8117726. Never invent fees, dates or promises.

Digital Skills Academy: 9 courses, 6 months each, 6,900 PKR or 30 USD per month. Mon-Thu, 1 hour per session, 10-20 students per batch. Live online and onsite.
Courses: Digital Marketing, Graphic Designing, Web Development, Video Editing & Animation, UI/UX Designing, E-Commerce Management, IT Fundamentals & Digital Literacy, Freelancing, AI & Automation.
Quran program for children aged 5-12: 6,900 PKR per month, 30 min sessions, Mon-Fri, 18 months (Noorani Qaida, Quran reading, Quran completion, Islamic studies throughout).
Other departments: Center for Personal Development (6 courses), Analytics & Business Intelligence (1), Islamic Studies & Languages (6). Details and fees via WhatsApp.
Careers: sales agents, instructors, admin and support. Email skillfilledacademia@gmail.com.
Contact: WhatsApp +92 302 8117726, email skillfilledacademia@gmail.com.`;

const json = (data, status = 200) => Response.json(data, { status });

async function askGemini(msgs, env) {
  const model = env.GEMINI_MODEL || "gemini-3.8-flash";
  const config = { maxOutputTokens: 600 };
  const level = env.GEMINI_THINKING ?? "low"; // 3.8 Flash has no "minimal"
  if (level) config.thinkingConfig = { thinkingLevel: level };
  const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-goog-api-key": env.GEMINI_API_KEY },
    body: JSON.stringify({
      systemInstruction: { parts: [{ text: KB }] },
      contents: msgs.map(m => ({ role: m.role === "user" ? "user" : "model", parts: [{ text: m.content }] })),
      generationConfig: config,
    }),
    signal: AbortSignal.timeout(25000),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
  const d = await r.json();
  return d.candidates?.[0]?.content?.parts?.[0]?.text;
}

async function askGroq(msgs, env) {
  const model = env.GROQ_MODEL || "openai/gpt-oss-120b";
  const body = {
    model,
    messages: [{ role: "system", content: KB }, ...msgs],
    max_completion_tokens: 500,
  };
  if (model.includes("gpt-oss")) body.reasoning_effort = "low"; // keep replies fast
  const r = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${env.GROQ_API_KEY}` },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(25000),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
  const d = await r.json();
  return d.choices?.[0]?.message?.content;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health") return new Response("ok");
    if (url.pathname !== "/api/chat") {
      return env.ASSETS ? env.ASSETS.fetch(request) : new Response("Not found", { status: 404 });
    }
    if (request.method !== "POST") return json({ error: "method not allowed" }, 405);

    // only accept calls coming from this site
    const origin = request.headers.get("Origin");
    if (origin && origin !== url.origin) return json({ error: "forbidden" }, 403);

    let data;
    try {
      data = await request.json();
    } catch {
      data = {};
    }
    const raw = data.messages;
    if (!Array.isArray(raw)) return json({ error: "bad input" }, 400);
    const msgs = raw
      .slice(-6)
      .filter(m => m && typeof m === "object")
      .map(m => ({ role: m.role === "user" ? "user" : "assistant", content: String(m.content ?? "").slice(0, 500) }));
    if (!msgs.length || msgs[msgs.length - 1].role !== "user") return json({ error: "bad input" }, 400);

    // try Gemini first, then Groq
    for (const [name, fn] of [["gemini", askGemini], ["groq", askGroq]]) {
      try {
        const reply = await fn(msgs, env);
        if (reply) return json({ reply: reply.trim(), via: name });
      } catch (e) {
        console.log(name, "failed:", e.message);
      }
    }
    return json({ error: "unavailable" }, 502);
  },
};
