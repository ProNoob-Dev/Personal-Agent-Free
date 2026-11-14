import json
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

DB = os.getenv("DATABASE_PATH", "./nexus.db")
PROVIDERS = {
    "cloudflare": "@cf/meta/llama-3.1-8b-instruct",
    "huggingface": "Qwen/Qwen2.5-7B-Instruct",
    "openrouter": "openai/gpt-4o-mini",
}

def connection():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=20)
    db.row_factory = sqlite3.Row
    return db

@asynccontextmanager
async def lifespan(app):
    with connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL,
            model TEXT NOT NULL, system_prompt TEXT NOT NULL,
            temperature REAL NOT NULL DEFAULT 0.7, created_at INTEGER NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, role TEXT NOT NULL,
            content TEXT NOT NULL, created_at INTEGER NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, provider TEXT NOT NULL,
            latency_ms INTEGER NOT NULL, created_at INTEGER NOT NULL)""")
        if not db.execute("SELECT 1 FROM agents LIMIT 1").fetchone():
            for name, prompt in [
                ("Research Agent", "You are a rigorous research assistant. Clearly distinguish facts from uncertainty."),
                ("Coding Agent", "You are a senior software engineer. Produce secure, maintainable code."),
                ("Writing Agent", "You are a clear, concise writing assistant."),
            ]:
                db.execute("INSERT INTO agents VALUES (?,?,?,?,?,?,?)", (
                    str(uuid.uuid4()), name, "cloudflare", PROVIDERS["cloudflare"],
                    prompt, 0.7, int(time.time())))
    yield

app = FastAPI(title="NEXUS AI", version="0.1.0", lifespan=lifespan)

def authorize(key: str | None):
    expected = os.getenv("ADMIN_API_KEY")
    if expected and key != expected:
        raise HTTPException(401, "Invalid API key")

class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    provider: str = "cloudflare"
    model: str = ""
    system_prompt: str = "You are a helpful assistant."
    temperature: float = Field(default=0.7, ge=0, le=2)

class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=30000)

def rowdict(row):
    return dict(row)

@app.get("/api/health")
def health():
    return {"ok": True, "service": "NEXUS AI"}

@app.get("/api/providers")
def providers(x_api_key: str | None = Header(default=None)):
    authorize(x_api_key)
    return [{"id": k, "suggested_model": v, "configured": bool(
        os.getenv({"cloudflare":"CLOUDFLARE_API_TOKEN", "huggingface":"HF_TOKEN", "openrouter":"OPENROUTER_API_KEY"}[k]))}
        for k, v in PROVIDERS.items()]

@app.get("/api/agents")
def list_agents(x_api_key: str | None = Header(default=None)):
    authorize(x_api_key)
    with connection() as db:
        return [rowdict(r) for r in db.execute("SELECT * FROM agents ORDER BY created_at, name")]

@app.post("/api/agents")
def create_agent(agent: AgentIn, x_api_key: str | None = Header(default=None)):
    authorize(x_api_key)
    if agent.provider not in PROVIDERS:
        raise HTTPException(400, "Unsupported provider")
    aid = str(uuid.uuid4())
    with connection() as db:
        db.execute("INSERT INTO agents VALUES (?,?,?,?,?,?,?)", (
            aid, agent.name, agent.provider, agent.model or PROVIDERS[agent.provider],
            agent.system_prompt, agent.temperature, int(time.time())))
    return {"id": aid}

@app.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: str, x_api_key: str | None = Header(default=None)):
    authorize(x_api_key)
    with connection() as db:
        deleted = db.execute("DELETE FROM agents WHERE id=?", (agent_id,)).rowcount
        db.execute("DELETE FROM messages WHERE agent_id=?", (agent_id,))
    if not deleted:
        raise HTTPException(404, "Agent not found")
    return {"deleted": True}

@app.get("/api/agents/{agent_id}/messages")
def messages(agent_id: str, x_api_key: str | None = Header(default=None)):
    authorize(x_api_key)
    with connection() as db:
        return [rowdict(r) for r in db.execute(
            "SELECT * FROM messages WHERE agent_id=? ORDER BY created_at, rowid LIMIT 100",
            (agent_id,))]

async def inference(agent, history):
    provider = agent["provider"]
    model = agent["model"]
    prompt = [{"role": "system", "content": agent["system_prompt"]}] + history
    async with httpx.AsyncClient(timeout=90) as client:
        if provider == "cloudflare":
            account = os.getenv("CLOUDFLARE_ACCOUNT_ID")
            token = os.getenv("CLOUDFLARE_API_TOKEN")
            if not account or not token:
                raise HTTPException(503, "Cloudflare credentials not configured")
            url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
            res = await client.post(url, headers={"Authorization": f"Bearer {token}"},
                json={"messages": prompt, "temperature": agent["temperature"]})
            res.raise_for_status()
            payload = res.json()
            return payload.get("result", {}).get("response", "")
        if provider == "huggingface":
            token = os.getenv("HF_TOKEN")
            if not token:
                raise HTTPException(503, "Hugging Face token not configured")
            url = "https://router.huggingface.co/v1/chat/completions"
        elif provider == "openrouter":
            token = os.getenv("OPENROUTER_API_KEY")
            if not token:
                raise HTTPException(503, "OpenRouter key not configured")
            url = "https://openrouter.ai/api/v1/chat/completions"
        else:
            raise HTTPException(400, "Unsupported provider")
        res = await client.post(url, headers={"Authorization": f"Bearer {token}"},
            json={"model": model, "messages": prompt, "temperature": agent["temperature"]})
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]

@app.post("/api/agents/{agent_id}/chat")
async def chat(agent_id: str, request: ChatIn, x_api_key: str | None = Header(default=None)):
    authorize(x_api_key)
    with connection() as db:
        agent = db.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
        if not agent:
            raise HTTPException(404, "Agent not found")
        history = [{"role": r["role"], "content": r["content"]} for r in db.execute(
            "SELECT role, content FROM messages WHERE agent_id=? ORDER BY created_at DESC, rowid DESC LIMIT 18",
            (agent_id,))][::-1]
    started = time.monotonic()
    try:
        answer = await inference(agent, history + [{"role": "user", "content": request.message}])
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Model provider returned HTTP {exc.response.status_code}")
    except httpx.RequestError:
        raise HTTPException(502, "Model provider connection failed")
    latency = round((time.monotonic() - started) * 1000)
    now = int(time.time())
    with connection() as db:
        for role, content in [("user", request.message), ("assistant", answer)]:
            db.execute("INSERT INTO messages VALUES (?,?,?,?,?)",
                (str(uuid.uuid4()), agent_id, role, content, now))
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), agent_id, agent["provider"], latency, now))
    return {"answer": answer, "latency_ms": latency, "provider": agent["provider"], "model": agent["model"]}

@app.get("/api/stats")
def stats(x_api_key: str | None = Header(default=None)):
    authorize(x_api_key)
    with connection() as db:
        return {
            "agents": db.execute("SELECT COUNT(*) FROM agents").fetchone()[0],
            "messages": db.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            "runs": db.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
            "average_latency_ms": round(db.execute("SELECT COALESCE(AVG(latency_ms),0) FROM runs").fetchone()[0]),
        }

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return Path(__file__).with_name("index.html").read_text(encoding="utf-8")
