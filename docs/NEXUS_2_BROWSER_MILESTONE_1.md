# Milestone 1 — Cloudflare Browser Run worker

## What this adds
- Creates a remote Chromium session on Cloudflare Browser Run.
- Connects from the FastAPI control plane using Playwright over CDP.
- Returns a Cloudflare live-view URL when the API includes one.
- Supports navigation, page inspection, visible screenshot capture, and bounded Browser Use read-only research tasks.
- Keeps sessions in process memory for this first milestone. Restarting the API or moving between multiple API instances will lose the in-memory mapping; durable session routing comes later.

## Cloudflare setup
Create a Cloudflare API token with **Browser Rendering - Edit** permission. Set:
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_BROWSER_RUN_TOKEN` (dedicated token for Browser Run)
- `ADMIN_API_KEY` (required by the browser endpoints)

Do not reuse a broad account API token. Keep these values in the backend's secret environment configuration, never in the frontend.

## AI engine setup
Browser Use is optional for deterministic browser navigation and inspection. Natural-language read-only browsing uses **Cloudflare Workers AI** directly through its OpenAI-compatible Chat Completions endpoint; OpenRouter is not used by this browser agent.

Set:
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_AI_API_TOKEN` (recommended dedicated token with Workers AI access; `CLOUDFLARE_API_TOKEN` is accepted as a fallback)
- `BROWSER_USE_MODEL` (defaults to `@cf/meta/llama-3.3-70b-instruct-fp8-fast`)

The AI token is separate from `CLOUDFLARE_BROWSER_RUN_TOKEN`; the latter needs **Browser Rendering - Edit** permission to create remote browser sessions.

## API
All endpoints require `X-API-Key: <ADMIN_API_KEY>`.

1. `GET /api/browser/health`
2. `POST /api/browser/sessions` with `{"url":"https://example.com"}`
3. `GET /api/browser/sessions/{session_id}/inspect`
4. `POST /api/browser/sessions/{session_id}/navigate` with `{"url":"https://www.cloudflare.com"}`
5. `POST /api/browser/sessions/{session_id}/agent-task` with `{"task":"Search for the latest public Cloudflare Browser Run docs","max_steps":5}`
6. `DELETE /api/browser/sessions/{session_id}`

The inspect response contains `screenshot_base64`, page text, links, current URL, title and (when provided) the Cloudflare live-view URL.

## Safety boundary
Milestone 1 is intentionally read-only. It blocks non-HTTP(S), localhost, private, loopback, link-local, reserved and non-public DNS targets, including subresources and redirects. Browser Use is instructed not to log in, submit forms, send messages, make purchases, upload/download files, accept terms, solve CAPTCHAs, or bypass website protections. These controls are a starting layer, not a substitute for production network egress controls and per-user authorization.

## Run and test
Install dependencies, set the environment variables, then start the existing app:
```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
pytest -q
```

## Known limitations
- No browser UI embed yet; use the returned Cloudflare live-view URL.
- Sessions are process-local and single-instance only.
- No durable queue, multi-tenant session ownership, approval workflow, or job application workflow yet.
- The existing FastAPI app still needs a Python-capable host. Cloudflare Browser Run hosts Chromium; it does not by itself host this Python app.
- Public website automation must respect each website's terms and access restrictions.
