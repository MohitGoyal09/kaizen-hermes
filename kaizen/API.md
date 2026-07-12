# Kaizen Backend — API Reference

> The FastAPI control plane for the Kaizen multi-tenant AI marketing agency. This is the **only** surface the frontend talks to (it never calls Hermes/Convex directly for agent work). Frontend lives in a separate repo — this doc is the contract.
>
> Companion: `kaizen/BACKEND_HANDOFF.md` (how to run + env + integrate). Last updated 2026-07-12.

## Base URL
- Local dev: `http://127.0.0.1:8000` (`KAIZEN_API_HOST` / `KAIZEN_API_PORT`).
- All routes are under `/v1`.

## Authentication (every route)
- The frontend signs in via **Convex Auth** and receives a **JWT**.
- Send it on every request: `Authorization: Bearer <jwt>`.
- The backend verifies the JWT against Convex's **JWKS** and derives **`tenant_id` from the `sub` claim, server-side**. The client never sends a trusted `tenant_id`/`brand_id` — any such value is only a *hint* that must equal the token's tenant.
- **One user = one brand = one tenant** (demo model).

**Auth errors**
| Status | When |
|---|---|
| `401 Unauthorized` | missing/malformed `Authorization` header, or token fails verification (bad signature, wrong `iss`/`aud`, expired) |
| `403 Forbidden` | valid token, but the `brand_id`/`job_id` in the path belongs to a **different** tenant |
| `404 Not Found` | the `brand_id`/`job_id` does not exist |

> ⚠️ **CORS is not enabled yet** (deferred). For local browser testing use a dev proxy or same-origin; `curl`/server-side calls work now.

---

## Routes

### `POST /v1/brands` — create a brand (provision its tenant)
Creates a brand for the authenticated tenant, provisions its isolated `HERMES_HOME`, and registers a skeleton profile. `brand_id` is **server-generated** (never client-supplied).

**Request body**
```json
{ "url": "https://acme.com" }
```
**`201 Created`**
```json
{ "brand_id": "a1b2c3…", "home": "/…/profiles/a1b2c3…", "status": "provisioned" }
```

### `GET /v1/brands/{brand_id}` — brand detail
**`200 OK`**
```json
{ "brand_id": "a1b2c3…", "tenant_id": "user_…", "url": "https://acme.com", "home": "/…", "status": "provisioned" }
```
Errors: `404` unknown, `403` other tenant.

### `POST /v1/brands/{brand_id}/onboard` — run onboarding
Enqueues an **onboarding job**: the Brand Strategist researches the brand URL (web tools), writes the brand DNA to `AGENTS.md`, and syncs it to Convex. Returns immediately with a `job_id`; watch progress via the stream route.

**`202 Accepted`**
```json
{ "job_id": "j_…", "status": "queued" }
```
Errors: `404` / `403`.

### `GET /v1/jobs/{job_id}` — job status
**`200 OK`**
```json
{ "job_id": "j_…", "status": "running", "type": "onboarding", "brand_id": "a1b2c3…", "error": null }
```
`status` ∈ `queued` | `running` | `done` | `failed`. Errors: `404` / `403`.

### `GET /v1/jobs/{job_id}/stream` — live event stream (SSE)
`Content-Type: text/event-stream`. Emits one `data: <json>\n\n` per event; **replays** any events buffered before you connected, then tails live; **terminates** after a `final` or `error` event. This powers the live run-tree / observability panel.

**Event envelope** (every line): `{ "type": <string>, "ts": <float>, "data": { … } }`

| `type` | `data` shape |
|---|---|
| `step` | `{ "iteration": int }` |
| `tool_start` | `{ "name": str, "args": any }` |
| `tool_complete` | `{ "name": str, "args": any, "result": any }` |
| `text_delta` | `{ "delta": str }` (assistant text, streamed) |
| `final` | `{ "final_response": str, "completed": bool, "cwd": str, "hermes_home": str }` |
| `error` | `{ "message": str }` |

> ⚠️ **SSE + auth caveat for the frontend:** browser `EventSource` **cannot set an `Authorization` header**. Since `/stream` requires the Bearer token, consume it with **`fetch()` + a `ReadableStream` reader** (which can set headers) rather than `EventSource`. (If needed we can add `?token=` query support later.)

---

## Example

```bash
# create a brand
curl -sX POST http://127.0.0.1:8000/v1/brands \
  -H "Authorization: Bearer $JWT" -H "Content-Type: application/json" \
  -d '{"url":"https://acme.com"}'

# start onboarding, then stream it
curl -sX POST http://127.0.0.1:8000/v1/brands/$BRAND/onboard -H "Authorization: Bearer $JWT"
curl -sN http://127.0.0.1:8000/v1/jobs/$JOB/stream -H "Authorization: Bearer $JWT"
```

```js
// Frontend SSE with auth (EventSource can't set headers — use fetch)
const res = await fetch(`${API}/v1/jobs/${jobId}/stream`, {
  headers: { Authorization: `Bearer ${jwt}` },
});
const reader = res.body.getReader();
const decoder = new TextDecoder();
for (;;) {
  const { value, done } = await reader.read();
  if (done) break;
  for (const line of decoder.decode(value).split("\n")) {
    if (line.startsWith("data: ")) {
      const ev = JSON.parse(line.slice(6));
      // ev.type: step | tool_start | tool_complete | text_delta | final | error
    }
  }
}
```

## Job model (internal shape)
`{ job_id, tenant_id, type, status, brand_id, error, events[] }` — `events[]` is the recorded event log the stream replays from.
