// convex/schema.ts
//
// Kaizen foundation-slice schema.
//
// Convex API grounding: fetched 2026-07-12 via Context7 (`/llmstxt/convex_dev_llms-full_txt`,
// `/get-convex/convex-auth`). `defineSchema` / `defineTable` / `.index(...)` signatures below
// match https://docs.convex.dev/database/reading-data and https://docs.convex.dev/llms-full.txt.
//
// TENANCY RULE (SPEC.md R7 / DEPLOYMENT.md "Convex changes the mechanism"):
//   Every table that holds tenant data carries a `tenantId: v.string()` field, set ONLY from
//   `ctx.auth.getUserIdentity().subject` inside a mutation/query (see convex/brands.ts,
//   convex/profile.ts, convex/jobs.ts). NEVER accept tenantId as a function argument from the
//   client. Every tenant-scoped table is indexed `by_tenant` (or `by_tenant_and_<field>`) so
//   every list/get query can (and must) use `.withIndex("by_tenant", q => q.eq("tenantId", tenantId))`
//   instead of an unindexed `.filter(...)`.
//
// One user = one brand = one tenant for the foundation slice (FOUNDATION_SLICE.md §4), but the
// schema does not hard-code that: `brands` is a list per tenant so the 1:1 rule can relax later
// without a migration.

import { defineSchema, defineTable } from "convex/server";
import { authTables } from "@convex-dev/auth/server";
import { v } from "convex/values";

export default defineSchema({
  // ---------------------------------------------------------------------
  // authTables — users/sessions/accounts/etc. tables required by
  // @convex-dev/auth (convex/auth.ts). Verified against current docs
  // (Context7 `/get-convex/convex-auth`, docs/pages/setup.mdx, 2026-07-12):
  // without these tables, convexAuth's Password provider has nowhere to
  // persist identities and every sign-in call throws.
  // ---------------------------------------------------------------------
  ...authTables,

  // ---------------------------------------------------------------------
  // brands — one row per brand a tenant owns/onboarded.
  // ---------------------------------------------------------------------
  brands: defineTable({
    tenantId: v.string(), // derived from ctx.auth.getUserIdentity().subject — never client-supplied
    name: v.string(),
    url: v.string(),
    status: v.union(
      v.literal("provisioning"),
      v.literal("onboarding"),
      v.literal("active"),
      v.literal("archived"),
    ),
    createdAt: v.number(), // Date.now() at insert time
  })
    .index("by_tenant", ["tenantId"])
    .index("by_tenant_and_status", ["tenantId", "status"]),

  // ---------------------------------------------------------------------
  // brandProfile — canonical brand DNA. System of record for structured
  // brand config (FOUNDATION_SLICE.md §1, §3; DEPLOYMENT.md "two different
  // brand profiles, do not conflate"). The Python backend's `render_home()`
  // projects this row to SOUL.md + AGENTS.md in $HERMES_HOME, and reconciles
  // file edits back via `upsertBrandProfile` after a run. One profile per
  // brand, so it is looked up (and upserted) by (tenantId, brandId).
  // ---------------------------------------------------------------------
  brandProfile: defineTable({
    tenantId: v.string(), // derived from auth identity, never client-supplied
    brandId: v.id("brands"),
    positioning: v.string(),
    voiceTone: v.string(),
    audience: v.string(),
    dos: v.array(v.string()),
    donts: v.array(v.string()),
    guardrails: v.array(v.string()),
    channels: v.array(v.string()),
    updatedAt: v.number(),
  })
    .index("by_tenant", ["tenantId"])
    .index("by_brand", ["brandId"])
    .index("by_tenant_and_brand", ["tenantId", "brandId"]),

  // ---------------------------------------------------------------------
  // campaigns — a content campaign scoped to a brand.
  // ---------------------------------------------------------------------
  campaigns: defineTable({
    tenantId: v.string(),
    brandId: v.id("brands"),
    name: v.string(),
    goal: v.optional(v.string()),
    status: v.union(
      v.literal("draft"),
      v.literal("active"),
      v.literal("completed"),
      v.literal("archived"),
    ),
    createdAt: v.number(),
  })
    .index("by_tenant", ["tenantId"])
    .index("by_tenant_and_brand", ["tenantId", "brandId"]),

  // ---------------------------------------------------------------------
  // posts — generated content pieces, optionally tied to a campaign.
  // ---------------------------------------------------------------------
  posts: defineTable({
    tenantId: v.string(),
    brandId: v.id("brands"),
    campaignId: v.optional(v.id("campaigns")),
    channel: v.string(), // e.g. "x", "telegram", "blog"
    body: v.string(),
    mediaUrl: v.optional(v.string()),
    status: v.union(
      v.literal("draft"),
      v.literal("scheduled"),
      v.literal("published"),
      v.literal("failed"),
    ),
    publishedAt: v.optional(v.number()),
    createdAt: v.number(),
  })
    .index("by_tenant", ["tenantId"])
    .index("by_tenant_and_brand", ["tenantId", "brandId"])
    .index("by_tenant_and_campaign", ["tenantId", "campaignId"]),

  // ---------------------------------------------------------------------
  // jobs — async work units (onboarding runs, content generation, publish,
  // eval). FastAPI enqueues via createJob, worker reports progress via
  // updateJobStatus, frontend polls/subscribes via getJob.
  // ---------------------------------------------------------------------
  jobs: defineTable({
    jobId: v.string(), // stable external id (e.g. uuid) surfaced to FastAPI/frontend
    tenantId: v.string(),
    brandId: v.optional(v.id("brands")),
    type: v.string(), // e.g. "onboarding", "content_generation", "publish", "eval"
    status: v.union(
      v.literal("queued"),
      v.literal("running"),
      v.literal("done"),
      v.literal("failed"),
    ),
    error: v.optional(v.string()),
    result: v.optional(v.any()),
    createdAt: v.number(),
    updatedAt: v.number(),
  })
    .index("by_tenant", ["tenantId"])
    .index("by_jobId", ["jobId"])
    .index("by_tenant_and_status", ["tenantId", "status"])
    .index("by_tenant_and_brand", ["tenantId", "brandId"]),

  // ---------------------------------------------------------------------
  // eval_runs — predicted vs. actual performance scoring for a post
  // (the closed-loop eval/observability differentiator, SPEC.md §7).
  // ---------------------------------------------------------------------
  eval_runs: defineTable({
    tenantId: v.string(),
    brandId: v.id("brands"),
    postId: v.id("posts"),
    predictedScore: v.optional(v.number()),
    actualScore: v.optional(v.number()),
    rationale: v.optional(v.string()),
    createdAt: v.number(),
  })
    .index("by_tenant", ["tenantId"])
    .index("by_tenant_and_post", ["tenantId", "postId"]),

  // ---------------------------------------------------------------------
  // engagement — real engagement metrics pulled back from a channel for a
  // published post.
  // ---------------------------------------------------------------------
  engagement: defineTable({
    tenantId: v.string(),
    brandId: v.id("brands"),
    postId: v.id("posts"),
    channel: v.string(),
    likes: v.optional(v.number()),
    shares: v.optional(v.number()),
    comments: v.optional(v.number()),
    impressions: v.optional(v.number()),
    fetchedAt: v.number(),
  })
    .index("by_tenant", ["tenantId"])
    .index("by_tenant_and_post", ["tenantId", "postId"]),
});
