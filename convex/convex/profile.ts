// convex/profile.ts
//
// Tenant-scoped queries/mutations for the `brandProfile` table — the
// canonical brand DNA system of record (FOUNDATION_SLICE.md §1, §3).
//
// `upsertBrandProfile` is called by the FastAPI backend AFTER a Hermes run:
// the worker writes brand DNA into SOUL.md/AGENTS.md during the run (files
// are authoritative mid-run), then the backend reads the file and reconciles
// it back into Convex so the structured data stays durable + queryable
// (FOUNDATION_SLICE.md §3: "After a run: the backend reconciles file →
// Convex"). `getBrandProfile` is what `render_home()` reads from on
// cold-start to re-materialize SOUL.md/AGENTS.md (Convex → file direction).
//
// SPEC.md R7: tenantId is derived from ctx.auth.getUserIdentity() only.
// FastAPI's service call to Convex must itself carry a Convex-verifiable
// identity (e.g. acting on behalf of the tenant via an actions/HTTP-action
// bridge, or — for the foundation slice — the FastAPI service authenticates
// to Convex using the same tenant's session token it already verified via
// JWKS). Either way, this file never accepts a raw tenantId argument.
//
// Convex API grounding: fetched 2026-07-12 via Context7
// (`/llmstxt/convex_dev_llms-full_txt`), matching current
// query/mutation/args/returns/ctx.db signatures.

import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

async function requireTenantId(ctx: { auth: { getUserIdentity: () => Promise<{ subject: string } | null> } }) {
  const identity = await ctx.auth.getUserIdentity();
  if (identity === null) {
    throw new Error("Unauthenticated: no valid identity on request");
  }
  return identity.subject;
}

const brandProfileFields = {
  positioning: v.string(),
  voiceTone: v.string(),
  audience: v.string(),
  dos: v.array(v.string()),
  donts: v.array(v.string()),
  guardrails: v.array(v.string()),
  channels: v.array(v.string()),
};

const brandProfileObject = v.object({
  _id: v.id("brandProfile"),
  _creationTime: v.number(),
  tenantId: v.string(),
  brandId: v.id("brands"),
  ...brandProfileFields,
  updatedAt: v.number(),
});

/**
 * Create or update the brand profile for a given brand. This is the
 * canonical brand-DNA write path: called at brand creation (skeleton
 * profile) and by the FastAPI reconciliation step after every onboarding /
 * editing run (file -> Convex sync-back).
 */
export const upsertBrandProfile = mutation({
  args: {
    brandId: v.id("brands"),
    ...brandProfileFields,
  },
  returns: v.id("brandProfile"),
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);

    const brand = await ctx.db.get("brands", args.brandId);
    if (brand === null || brand.tenantId !== tenantId) {
      throw new Error("Brand not found for this tenant");
    }

    const existing = await ctx.db
      .query("brandProfile")
      .withIndex("by_tenant_and_brand", (q) =>
        q.eq("tenantId", tenantId).eq("brandId", args.brandId),
      )
      .unique();

    const fields = {
      positioning: args.positioning,
      voiceTone: args.voiceTone,
      audience: args.audience,
      dos: args.dos,
      donts: args.donts,
      guardrails: args.guardrails,
      channels: args.channels,
      updatedAt: Date.now(),
    };

    if (existing === null) {
      return await ctx.db.insert("brandProfile", {
        tenantId,
        brandId: args.brandId,
        ...fields,
      });
    }

    await ctx.db.patch("brandProfile", existing._id, fields);
    return existing._id;
  },
});

export const getBrandProfile = query({
  args: {
    brandId: v.id("brands"),
  },
  returns: v.union(brandProfileObject, v.null()),
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);

    const profile = await ctx.db
      .query("brandProfile")
      .withIndex("by_tenant_and_brand", (q) =>
        q.eq("tenantId", tenantId).eq("brandId", args.brandId),
      )
      .unique();

    return profile;
  },
});
