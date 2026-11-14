# NEXUS AI

A personal AI agent workspace with a responsive dark dashboard and a FastAPI backend.

## Included in this MVP
- Agent creation, deletion, and per-agent model/provider/system-prompt settings
- Chat and local SQLite conversation persistence
- Cloudflare Workers AI, Hugging Face Inference Providers, and OpenRouter adapters
- Basic run-count and latency metrics
- Optional shared API key (set ADMIN_API_KEY)
- Dockerfile and Docker Compose for a Python container deployment

## Run locally
Requires Python 3.11+.

```bash
python -m venv .venv
# activate .venv
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 and http://localhost:8000/docs.

## Configure model providers
Populate only the credentials you intend to use in your deployment environment:
- Cloudflare: CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN
- Hugging Face: HF_TOKEN
- OpenRouter: OPENROUTER_API_KEY

Model IDs are editable per agent. Provider availability, model compatibility and pricing can change; the suggested defaults are examples, not guaranteed free offerings.

## Container deployment
```bash
docker compose up --build -d
```
Create a local .env first. Docker Compose uses a persistent volume for SQLite.

## Status and limitations
**Code has been committed, but has not yet been deployed or end-to-end tested.**
This is an MVP, not the complete multi-agent platform. Agent-to-agent orchestration, MCP tools, RAG, background jobs, multi-user authentication, tenant isolation, streaming, billing, and full production monitoring are not yet implemented.

The Python + SQLite app is **not** a Cloudflare Workers deployment. You can use Cloudflare Workers AI as an inference provider, but hosting this app requires a Python-capable host with persistent storage or a future Cloudflare-native rewrite.

**Security:** Never commit secrets. Set ADMIN_API_KEY for an initial private deployment, and implement proper authentication, authorization, rate limiting, backups and abuse controls before public access.
