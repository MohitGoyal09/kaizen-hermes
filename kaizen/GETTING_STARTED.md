# Getting Started — config, API timing, power-ups

> Start-of-build reference. You are ready to build; the two spikes below are the first tasks, not more planning.

## Readiness verdict
Ready. Locked docs: `SPEC` (auth/tenancy), `BUILD_PLAN` (phases), `DEPLOYMENT` (Convex + Honcho + profiles), `FEATURES_AND_AGENTS` (roster + onboarding). Kill the two unknowns first, then everything is mechanical:
1. **Isolation spike** — two tenant workers (`HERMES_HOME` env), assert no cross-tenant rows.
2. **Programmatic invocation spike** — confirm the exact call to run a Hermes agent + read its run events from FastAPI.

## Hermes config to start (grounded in `cli-config.yaml.example`)

Per profile (`$HERMES_HOME/config.yaml`):
- **Model** — `model.default` + `model.base_url` + key. Point at OpenAI (use the $200 OpenAI perk) or OpenRouter. `hermes model` to switch.
- **Memory** — keep `memory.memory_enabled: true`, `user_profile_enabled: true`. Run `hermes memory setup honcho`, set `memory.provider: honcho`, and `honcho.json` with Honcho **Cloud** base URL + key. (Durable memory in the cloud, per tenant.)
- **MCP tools** — connect the **X MCP server** (and blog API) per the MCP guide; Hermes is an MCP client. Each specialist gets the MCP tools its job needs.
- **Skills** — author one skill per specialist role (agentskills.io format): the system prompt + tools that define that agent's job.
- **Backend / deploy** — `terminal.backend: local` for dev; `docker` / `modal` / `daytona` for deploy. `container_persistent: true` so state survives. One profile per tenant under `HERMES_HOME`.
- **Concurrency** — set `max_concurrent_sessions` (defaults null); size it for the demo's parallel tenants.
- **Gateway + cron** — run `gateway run` and set a cron so a **Hermes capability does real work live** (Telegram entry + a scheduled post). This is the rule-03 proof; don't skip it.

## When to build the API layer
**Right after the two spikes, in Phase 1, concurrent with the first agent.** Not before (nothing to expose), not after the agents (the frontend needs it). The API + job contract is already frozen in `SPEC §5`, so **frontend and backend start now against mocks** and meet at the contract.

## Power-ups → agents (each +25, all six = +150; a mentor must see each working live)

| Power-up | Where it works in our build | Agent / surface | Evidence |
|---|---|---|---|
| **Linkup** | Brand research + competitor top-content search | Brand Strategist + Competitor Analyst | live query in the run trace |
| **Convex** | App DB + realtime dashboard/run-tree | control plane + frontend | repo + Convex dashboard |
| **ElevenLabs** | Brand-voice audio in generated content | Content Creator | live audio in the product |
| **Cloudflare** | Host the frontend + API (the deployed link) | deploy | live URL + CF dashboard |
| **Dodo Payments** | Pay-per-use / plan unlock (live checkout) | Publisher / billing | live-mode checkout on stage |
| **Wispr Flow** | Voice onboarding intake (user dictates the brand brief), or team dictates 500+ words | Brand Strategist intake | Wispr stats (500+ words) |

Notes:
- **Dodo** also earns a cross-track **Revenue** bonus if a real checkout clears live (it ties to the pay-per-use tenancy).
- OpenAI credits are a perk (free compute), not a scored power-up.
- Rule for all: a mentor has to see it doing real work in the build, not just an activated account.

## Start here (first commands)
1. Install: one-line installer or `docker pull nousresearch/hermes-agent`.
2. `hermes model` → set OpenAI/OpenRouter + key. Smoke test one CLI turn.
3. `hermes memory setup honcho` → Honcho Cloud.
4. Run the **isolation spike**, then the **invocation spike**.
5. Stand up the deploy skeleton (Cloudflare + Convex) in parallel to get the link live early.
