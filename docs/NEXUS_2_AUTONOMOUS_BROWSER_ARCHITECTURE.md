# NEXUS AI 2.0 — Hybrid Autonomous Browser Architecture

## Goal
Extend the existing FastAPI + SQLite + dashboard MVP with a user-visible autonomous browser. Users describe outcomes in natural language; NEXUS plans work, executes safe browser actions, streams progress, and pauses for approval before consequential actions.

## Existing baseline
- FastAPI application in `app/main.py`
- Static dashboard in `app/index.html`
- SQLite persistence
- Cloudflare Workers AI, Hugging Face, and OpenRouter inference adapters
- Docker deployment with persistent `/data` volume

The current repository is an MVP. Browser automation, durable task orchestration, user authentication, streaming, and production isolation are not implemented yet.

## Target architecture

```text
Browser UI (dashboard)
  | REST + WebSocket/SSE
FastAPI control plane
  |-- Task API / state machine
  |-- Planner (LLM proposes structured steps)
  |-- Policy + approval gate
  |-- Event/audit log
  |-- Session manager
  |
Queue (Redis initially; durable queue in production)
  |
Isolated browser worker (Playwright + Chromium)
  |-- One isolated browser context per user/session
  |-- Allowlisted browser tools
  |-- Screenshot / page snapshot events
  |-- No arbitrary shell or unrestricted network access
  |
PostgreSQL (tasks, steps, approvals, sessions, audit)
Object storage (screenshots and user-approved artifacts)
Cloudflare edge (Workers/API routing, R2, Queues where appropriate)
Model providers (Cloudflare Workers AI / OpenRouter)
```

## Key design decision
Cloudflare Workers should remain the edge/control-plane and AI-inference integration layer. Do not attempt to run a full persistent Chromium/Playwright browser inside a standard Cloudflare Worker. Run Chromium in a dedicated container/browser service (for example, a private container service) and connect it to the FastAPI control plane over authenticated internal APIs.

## Hybrid task lifecycle
1. `queued`: task accepted and persisted.
2. `planning`: planner produces a structured plan with expected side effects.
3. `running`: worker executes permitted read-only and reversible steps.
4. `waiting_approval`: pause before sending messages, submitting applications/forms, purchases, deleting data, accepting legal terms, or other consequential actions.
5. `completed`, `failed`, or `cancelled`: terminal states with an audit trail.

Users can pause, resume, cancel, and take over a browser session. Approval is bound to a specific action payload and expires if the page or payload changes.

## Browser tool contract
Initial tools:
- `open_url(url)`
- `get_page_snapshot()`
- `click(selector_or_accessible_name)`
- `fill(selector_or_accessible_name, value)`
- `select_option(selector, value)`
- `upload_file(selector, approved_file_id)`
- `take_screenshot()`
- `request_approval(action_summary, exact_action)`

The model may select from these tools but cannot generate arbitrary Python, shell commands, or raw Playwright code. Validate URLs, restrict private/loopback/link-local IP ranges, re-check redirects, and apply an outbound domain policy to mitigate SSRF.

## Security requirements
- Never store website passwords or session cookies in plaintext application tables.
- Keep browser profiles isolated per user; encrypt session material and restrict access to the browser worker.
- Treat page content, emails, documents, and websites as untrusted data, not as instructions. Defend against prompt injection.
- Do not bypass CAPTCHAs, MFA, access controls, or site restrictions.
- Require explicit approval for consequential actions. Do not infer approval from a general task instruction.
- Enforce authentication, authorization, rate limits, task ownership, audit logs, and retention controls before public deployment.
- Restrict file uploads to user-selected files and approved paths; scan uploads and limit size/type.
- Use a kill switch and worker timeouts/resource limits.

## Data model (initial)
- `tasks`: id, owner_id, instruction, status, mode, created_at, updated_at
- `task_steps`: id, task_id, ordinal, description, tool_name, input_json, output_json, status
- `approvals`: id, task_id, step_id, action_hash, summary, status, expires_at, decided_at
- `browser_sessions`: id, owner_id, worker_session_ref, status, created_at, last_used_at
- `task_events`: id, task_id, event_type, payload_json, created_at

Use PostgreSQL for multi-user/production concurrency. SQLite may remain for local single-user development only.

## API surface (proposed)
- `POST /api/tasks` — create task
- `GET /api/tasks/{task_id}` — task status and plan
- `GET /api/tasks/{task_id}/events` — event stream
- `POST /api/tasks/{task_id}/pause`
- `POST /api/tasks/{task_id}/resume`
- `POST /api/tasks/{task_id}/cancel`
- `POST /api/tasks/{task_id}/approvals/{approval_id}` — approve/reject exact pending action
- `POST /api/browser-sessions` — create isolated browser session
- `GET /api/browser-sessions/{session_id}/view` — authenticated browser view/stream

## Delivery milestones
1. Browser worker proof of concept: open a URL, inspect page, click/fill, return screenshot and structured events.
2. Task state machine and durable persistence.
3. Dashboard task panel with live events and pause/cancel.
4. Approval UI bound to exact pending action.
5. Session persistence, isolation, observability and recovery.
6. Job-search workflow that collects listings and prepares applications; final application submission remains approval-gated.

## Acceptance criteria for milestone 1
- A task can launch an isolated Chromium context.
- Agent can navigate to a public URL and return page title, URL, snapshot and screenshot.
- Browser actions are tool-whitelisted and logged.
- User can stop the session.
- Unsafe URLs and private-network targets are rejected.
- No credentials are required for the initial public-site demo.
