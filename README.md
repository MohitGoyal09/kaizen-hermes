<p align="center">
  <img src="assets/banner.png" alt="Hermes Agent" width="100%">
</p>

# Kaizen x Hermes

> **Fork notice:** We cloned the Hermes Agent repository and built Kaizen on top of it. This repo is based on the Hermes/kaizen foundation and adapts Hermes into a multi-tenant AI marketing agency for brands.

[Hermes base](https://github.com/NousResearch/hermes-agent) | [Project spec](kaizen/SPEC.md) | [Build plan](kaizen/BUILD_PLAN.md) | [Getting started](kaizen/GETTING_STARTED.md)

**Kaizen x Hermes is an AI marketing agency built on Hermes Agent.** A brand owner connects a product or website, a crew of agents researches the brand, writes brand DNA, generates on-brand campaigns, publishes to real channels, measures engagement, and improves the next round.

Hermes gives the project its agent runtime: tool use, memory, skills, messaging gateways, cron jobs, subagents, and durable workflows. Kaizen turns that foundation into a focused product for D2C, ecommerce, and local brands that need strategy, creative, publishing, and evaluation in one loop.

---

## GrowthX Hermes Buildathon Proof

**How we used Hermes:** Hermes as the base harness.

This repository is the proof. We did not start from a blank app; we cloned the Hermes Agent codebase and built the Kaizen AI marketing-agency layer on top of it.

What a mentor should check on the floor:

1. **Hermes runtime is still present at the repo root.** The original Hermes structure is here: `agent/`, `hermes_cli/`, `gateway/`, `skills/`, `tools/`, `web/`, `apps/`, `docs/`, `tests/`, `pyproject.toml`, and the Hermes CLI/runtime files.
2. **Kaizen-specific project work lives under `kaizen/`.** Start with [kaizen/SPEC.md](kaizen/SPEC.md), [kaizen/BUILD_PLAN.md](kaizen/BUILD_PLAN.md), [kaizen/FEATURES_AND_AGENTS.md](kaizen/FEATURES_AND_AGENTS.md), [kaizen/CODE_GROUNDED_PLAN.md](kaizen/CODE_GROUNDED_PLAN.md), [kaizen/DEPLOYMENT.md](kaizen/DEPLOYMENT.md), and [kaizen/GETTING_STARTED.md](kaizen/GETTING_STARTED.md).
3. **The product design maps directly onto Hermes capabilities.** Kaizen uses Hermes concepts for agent orchestration, skills, memory, subagents, tool/MCP use, scheduled work, messaging gateways, and per-brand tenant isolation through `HERMES_HOME`.
4. **The intended user flow runs through Hermes.** Brand signup -> tenant Hermes profile -> Hermes worker -> specialist agents -> campaign drafts -> approval -> publish -> eval -> memory update.
5. **We disclosed the non-trivial base.** This is intentionally a Hermes-based project, not a hidden from-scratch clone.

In short: **Hermes is not just inspiration. Hermes is the base runtime and harness that Kaizen builds on.**

---

## What We Built

- **Multi-tenant brand workspaces** - every brand gets isolated Hermes state through its own `HERMES_HOME`.
- **Brand onboarding** - start from a URL, then let the Brand Strategist research, interview, and write brand DNA.
- **Agent crew** - orchestrator, brand strategist, competitor analyst, content creator, publisher, and eval agent roles.
- **Campaign generation** - create on-brand posts, ad angles, creative directions, and publishing drafts.
- **Real publishing loop** - publish to an actual surface, then track the post as real output instead of a static demo.
- **Eval loop** - predict performance, measure engagement, capture learnings, and feed the next campaign.
- **Dashboard-ready architecture** - frontend can subscribe to jobs, run trees, campaign state, and approvals.

---

## Why Hermes

Hermes is a self-improving AI agent with memory, skills, tools, automations, messaging gateways, and terminal backends. Kaizen uses those primitives directly:

| Hermes capability | Kaizen use |
| --- | --- |
| Agent runtime | Marketing agency orchestrator |
| Skills | Specialist marketing procedures |
| Memory | Brand DNA, guardrails, learnings, and user context |
| Subagents | Parallel specialist workstreams |
| Tools and MCP | Research, content generation, publishing, and analytics |
| Cron | Scheduled campaign refreshes and reports |
| Gateway | Multi-surface communication with the agency |
| Terminal backends | Local, Docker, cloud, and per-tenant worker execution |

Credit to the original Hermes Agent project by [Nous Research](https://nousresearch.com): [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).

---

## Repository Map

```text
.
|-- kaizen/
|   |-- SPEC.md                 # Product spec and judging strategy
|   |-- BUILD_PLAN.md           # Buildathon execution plan
|   |-- FEATURES_AND_AGENTS.md  # Agent crew and feature set
|   |-- CODE_GROUNDED_PLAN.md   # Hermes source-traced implementation plan
|   |-- DEPLOYMENT.md           # Cloud and tenant-state architecture
|   `-- GETTING_STARTED.md      # Practical first steps
|-- agent/                      # Hermes core agent code
|-- hermes_cli/                 # CLI entrypoints
|-- gateway/                    # Messaging gateway
|-- skills/                     # Hermes skills system
|-- tools/                      # Tool integrations
|-- web/                        # Hermes web dashboard
|-- apps/                       # Desktop and app surfaces
|-- docs/                       # Upstream Hermes docs
|-- tests/                      # Test suite
`-- README.md
```

---

## Kaizen Docs

Start here if you are working on the marketing-agency layer:

| Document | What it covers |
| --- | --- |
| [kaizen/SPEC.md](kaizen/SPEC.md) | Product thesis, buildathon track, core requirements, scoring strategy |
| [kaizen/BUILD_PLAN.md](kaizen/BUILD_PLAN.md) | Phase plan, ownership, risks, and demo path |
| [kaizen/FEATURES_AND_AGENTS.md](kaizen/FEATURES_AND_AGENTS.md) | Agent crew, handoffs, and role responsibilities |
| [kaizen/CODE_GROUNDED_PLAN.md](kaizen/CODE_GROUNDED_PLAN.md) | Implementation plan traced against Hermes source files |
| [kaizen/DEPLOYMENT.md](kaizen/DEPLOYMENT.md) | Convex, Honcho, FastAPI, Hermes workers, and tenant state |
| [kaizen/GETTING_STARTED.md](kaizen/GETTING_STARTED.md) | Practical setup sequence and first engineering spikes |

---

## Quick Install

This repo still runs as Hermes Agent. Use the Hermes installer for the managed runtime layout.

### Linux, macOS, WSL2, Termux

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

### Windows PowerShell

```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```

After installation:

```bash
source ~/.bashrc
hermes
```

For native development from this checkout:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv ~/.hermes/venvs/hermes-dev --python 3.11
source ~/.hermes/venvs/hermes-dev/bin/activate
uv pip install -e ".[all,dev]"
scripts/run_tests.sh
```

On Windows, use the native Hermes installer or WSL2 for the Linux-style development flow.

---

## Getting Started With Kaizen

1. Read [kaizen/SPEC.md](kaizen/SPEC.md) for the product contract.
2. Read [kaizen/BUILD_PLAN.md](kaizen/BUILD_PLAN.md) for the phase order.
3. Use [kaizen/CODE_GROUNDED_PLAN.md](kaizen/CODE_GROUNDED_PLAN.md) before touching Hermes internals.
4. Implement tenant isolation first: one active brand equals one isolated `HERMES_HOME`.
5. Wire onboarding next: URL -> brand profile -> campaign job -> generated output.
6. Keep the eval loop visible: predictions, real engagement, and learned updates are core to the product.

The intended API/product shape is:

```text
Brand signup -> tenant profile -> Hermes worker -> specialist agents
             -> campaign drafts -> approval -> publish -> eval -> memory update
```

---

## Target Backend Shape

The Kaizen layer is planned around:

- **FastAPI control plane** for product-facing routes and worker orchestration.
- **Convex** for structured product data: users, brands, campaigns, posts, jobs, eval runs, and engagement metrics.
- **Honcho Cloud** for durable Hermes memory and brand/user modeling.
- **Per-tenant Hermes profiles** for operational state, skills, config, and session isolation.
- **Frontend dashboard** for onboarding, campaign requests, approvals, run trees, and eval visibility.

See [kaizen/DEPLOYMENT.md](kaizen/DEPLOYMENT.md) for the full architecture.

---

## Hermes Commands

```bash
hermes             # Start the interactive CLI
hermes model       # Choose provider and model
hermes tools       # Configure enabled tools
hermes config set  # Set config values
hermes gateway     # Start messaging gateway
hermes setup       # Run setup wizard
hermes update      # Update Hermes
hermes doctor      # Diagnose issues
```

Full upstream docs: [hermes-agent.nousresearch.com/docs](https://hermes-agent.nousresearch.com/docs/)

---

## Current Status

- Hermes fork is present as the base runtime.
- Kaizen product spec and build plans live under `kaizen/`.
- Multi-tenant architecture is specified around per-brand Hermes profiles.
- Agent crew roles and handoffs are documented.
- Backend and dashboard implementation are planned but still need to be wired to the product surface.

---

## Contributing

For Hermes-level changes, follow the upstream [Contributing Guide](CONTRIBUTING.md).

For Kaizen product work, keep changes grounded in:

- [kaizen/SPEC.md](kaizen/SPEC.md)
- [kaizen/BUILD_PLAN.md](kaizen/BUILD_PLAN.md)
- [kaizen/CODE_GROUNDED_PLAN.md](kaizen/CODE_GROUNDED_PLAN.md)

Do not mix tenant data across brands. Tenant isolation is a first-class requirement.

---

## License

Hermes Agent is MIT licensed. See [LICENSE](LICENSE).

Built on Hermes Agent by [Nous Research](https://nousresearch.com), adapted by the Kaizen team for the AI marketing agency project.
