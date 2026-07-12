# Features & Sub-Agent Roster (LOCKED)

> The agency's declared job, its agents, and their profiles. Pairs with `SPEC.md`, `BUILD_PLAN.md`, `DEPLOYMENT.md`.

## Product flow (confirmed)

1. Brand pastes their **URL** (existing brand, LocalAds-style). Auth → tenant.
2. At **onboarding**, the orchestrator spawns the **Brand Strategist**, which researches the brand and writes a brand profile ("Business DNA") to per-tenant memory (Honcho).
3. Brand Strategist returns a **first report**: current positioning, voice/tone, visual identity, audience, channels, and **what to improve**.
4. **Competitor Analyst** pulls competitors and their top-performing content (Linkup) to set a real baseline.
5. **Content Creator** generates on-brand content matched to the brand profile.
6. **Publisher** posts it to a real surface (X / blog) — the shippable real output.
7. **Eval/Scorer** predicts performance vs the baseline, measures real engagement after, bounces weak drafts back, and captures failures as eval cases.
8. The user **chats with the main orchestrator**, which plans per request and spawns the specialists it needs.

## Declared job (what we complete end to end)
**Take a brand URL and publish an on-brand piece of content to a real surface, then measure it.** Research/audit/competitor are the upstream specialists that feed the publish. The published post is the 20x "real output."

## The roster: orchestrator + 5 specialists

| Agent | Job | Key inputs | Output (artifact) | Tools / MCP | Memory | Rubric it drives |
|---|---|---|---|---|---|---|
| **Orchestrator** (manager) | Chats with user, plans subtasks per request, spawns specialists, reviews outputs, escalates by exception | user message, brand profile | plan + delegated results | subagent spawn | reads brand profile | Org structure (5x), handoffs (2x) |
| **Brand Strategist** | Research the brand + audit current voice + suggest improvements (folds in positioning/idea check) | brand URL | brand profile written to memory + first report | web fetch, Linkup | **writes** brand DNA + guardrails | Real output (report), memory (2x) |
| **Competitor Analyst** | Find competitors + their top-performing content; set a performance baseline | brand profile, niche | competitor baseline | Linkup (+25) | reads brand, writes baseline | Real output, feeds eval |
| **Content Creator** | Generate on-brand content matched to the profile (text + image + brand voice) | brand profile, baseline | draft content pieces | image gen, ElevenLabs (+25) | reads brand DNA | Real output (20x) |
| **Publisher** | Post approved content to a real surface | approved content | **real published post URL** | X MCP / blog API, per-tenant creds | reads connected account | **Real output (20x)** |
| **Eval/Scorer** | Predict vs baseline before posting; measure real engagement after; bounce weak drafts; capture failures | content, baseline, live metrics | scores + revision notes + new eval cases | metrics fetch, Langfuse | reads/writes performance history | **Eval (5x), observability (7x)** |

Each specialist is a Hermes subagent/profile-scoped role: a system prompt (its job), its skills, its MCP tools, and read/write scope to the tenant's memory. The orchestrator spawns them; they share the tenant's memory (not separate profiles) per SPEC R4.

## Feature → agent map
- **Idea/positioning validation** → folded into Brand Strategist (positioning check).
- **Brand research + voice audit + improvement report** → Brand Strategist.
- **Competitor analysis** → Competitor Analyst.
- **Content creation (on-brand)** → Content Creator.
- **Publish + measure** → Publisher + Eval/Scorer.
- **Chat + orchestration** → Orchestrator.

## Build order (time-boxed)
1. **Isolation spike** (gate) — from BUILD_PLAN Phase 0.
2. **Thinnest real slice** — Orchestrator → Content Creator → Publisher → **one real post**. Proves 20x floor before anything else.
3. **Brand Strategist at onboarding** — so content is actually on-brand (reads the profile).
4. **Competitor Analyst + Eval/Scorer** — the differentiator loop (predict → measure → improve).
5. **Management UI + cost tuning + demo proof.**

Do NOT build all six agents before the first real post exists. Slice 2 is the make-or-break.

## Level target per agent (rubric)
- Publisher/Content → Working output **L4** (real surface, human approves publish), reach **L5** (auto-publish, escalate by exception).
- Orchestrator → org **L4** (dynamic plan + bounce-back), reach **L5** (spawn a specialist on the fly, e.g. a video specialist).
- Eval/Scorer → eval **L4→L5**, observability **L4→L5**.
- Brand Strategist → memory **L5** (three layers: now + brand's past + brand rules).

## Open decision (default chosen, flag to change)
- **Publish approval:** default **human approves before publish (L4)**. Flip to auto-publish + exception escalation (L5) only once eval is trusted. Safer for the demo, and a mentor approving live still scores L4.
