"""CropMemory MVP - Problem -> Evidence -> Decision -> Outcome -> Memory"""
import json, os, sqlite3
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

BASE = Path(__file__).parent
DB = BASE / "cropmemory.db"
MODEL = os.getenv("CM_MODEL", "claude-sonnet-5-5")
app = FastAPI(title="CropMemory MVP")

def conn():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def init_db():
    with conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS cases(id INTEGER PRIMARY KEY AUTOINCREMENT,
            crop TEXT, soil TEXT, weather TEXT, problem TEXT, action TEXT, outcome TEXT,
            result TEXT, source TEXT DEFAULT 'seed')""")
        if c.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0:
            for r in json.loads((BASE / "data/cases.json").read_text()):
                c.execute("INSERT INTO cases(crop,soil,weather,problem,action,outcome,result) VALUES(?,?,?,?,?,?,?)",
                          (r["crop"], r["soil"], r["weather"], r["problem"], r["action"], r["outcome"], r["result"]))

ADVISORIES = json.loads((BASE / "data/advisories.json").read_text())
idx = {}

def build_index():
    with conn() as c:
        cases = [dict(r) for r in c.execute("SELECT * FROM cases")]
    docs = [f'{x["problem"]} {x["action"]}' for x in cases]
    v = TfidfVectorizer(ngram_range=(1, 2), stop_words="english").fit(
        docs + [f'{a["title"]} {a["text"]}' for a in ADVISORIES])
    idx.update(v=v, cases=cases, cm=v.transform(docs),
               am=v.transform([f'{a["title"]} {a["text"]}' for a in ADVISORIES]))

def rank(q, crop, matrix, items, k, soil="", weather="", thr=0.12):
    sims = cosine_similarity(idx["v"].transform([q]), matrix)[0]
    out = []
    for s, it in zip(sims, items):
        s = float(s)
        if s > thr and it["crop"].lower() == crop.lower():
            bonus = (0.1 if soil and soil.lower() == it.get("soil", "").lower() else 0) + \
                    (0.05 if weather and set(weather.lower().replace(",", " ").split()) & set(it.get("weather", "").lower().replace(",", " ").split()) else 0)
            out.append({**it, "score": round(min(s * 2 + 0.2 + bonus, 0.99), 2)})
    return sorted(out, key=lambda x: -x["score"])[:k]

def options_from(cases):
    g = {}
    for c in cases:
        o = g.setdefault(c["action"], {"action": c["action"], "n": 0, "worked": 0, "partial": 0, "failed": 0})
        o["n"] += 1; o[c["result"]] += 1
    for o in g.values():
        o["success_pct"] = round(100 * (o["worked"] + 0.5 * o["partial"]) / o["n"])
    return sorted(g.values(), key=lambda o: (-o["success_pct"], -o["n"]))

def offline_insight(q, advs, cases, opts):
    if not cases and not advs:
        return "No close match yet. Consult your local KVK, then record your outcome so the next farmer benefits."
    parts = []
    if advs: parts.append(f'Trusted source ({advs[0]["title"]}): {advs[0]["text"].split(". ")[0].rstrip(".")}.')
    if opts:
        b = opts[0]; parts.append(f'Among {len(cases)} similar farmer cases, "{b["action"]}" had the best record '
                                  f'({b["worked"]} worked, {b["partial"]} partial, {b["failed"]} failed).')
    bad = [o for o in opts if o["failed"] and not o["worked"]]
    if bad: parts.append(f'Caution: "{bad[0]["action"]}" did not work for others in similar conditions.')
    parts.append("Final decision is yours - confirm doses with your local agriculture officer.")
    return " ".join(parts)

def llm_insight(q, advs, cases):
    import anthropic
    ctx = "TRUSTED ADVISORIES:\n" + "\n".join(f'- {a["title"]}: {a["text"]}' for a in advs)
    ctx += "\nSIMILAR FARMER CASES:\n" + "\n".join(
        f'- action: {c["action"]} | outcome: {c["outcome"]} | result: {c["result"]}' for c in cases)
    prompt = (f"A farmer reports: {q}\n\n{ctx}\n\nIn under 90 words, compare the advisories with the farmer experiences. "
              "Say what worked, what failed, and suggest the best-supported option. Mention if experiences conflict with advisories. "
              "Use only the evidence above. End by reminding the farmer to confirm doses with local experts.")
    m = anthropic.Anthropic().messages.create(model=MODEL, max_tokens=300, messages=[{"role": "user", "content": prompt}])
    return m.content[0].text

class Query(BaseModel):
    crop: str; soil: str = ""; weather: str = ""; problem: str

class Outcome(Query):
    action: str; outcome: str = ""; result: str = "worked"

@app.post("/api/advise")
def advise(q: Query):
    text = f"{q.crop} {q.soil} {q.weather} {q.problem}"
    cases = rank(q.problem, q.crop, idx["cm"], idx["cases"], 5, q.soil, q.weather)
    advs = rank(q.problem, q.crop, idx["am"], ADVISORIES, 2, thr=0.05)
    opts = options_from(cases)
    mode, insight = "offline", offline_insight(text, advs, cases, opts)
    if os.getenv("ANTHROPIC_API_KEY") and (cases or advs):
        try: insight, mode = llm_insight(text, advs, cases), "ai"
        except Exception as e: print("LLM fallback:", e)
    return {"advisories": advs, "cases": cases, "options": opts[:4], "insight": insight, "mode": mode, "memory_count": len(idx["cases"])}

@app.post("/api/outcome")
def outcome(o: Outcome):
    with conn() as c:
        c.execute("INSERT INTO cases(crop,soil,weather,problem,action,outcome,result,source) VALUES(?,?,?,?,?,?,?,'farmer')",
                  (o.crop, o.soil, o.weather, o.problem, o.action, o.outcome, o.result))
    build_index()
    return {"memory_count": len(idx["cases"])}

@app.get("/api/stats")
def stats():
    return {"memory_count": len(idx["cases"]), "crops": sorted({c["crop"] for c in idx["cases"]})}

@app.post("/api/reset")
def reset():
    DB.unlink(missing_ok=True); init_db(); build_index(); return stats()

init_db(); build_index()
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

@app.get("/")
def home(): return FileResponse(BASE / "static/index.html")
