// convex/brands.ts
//
// Tenant-scoped queries/mutations for the `brands` table.
//
// SPEC.md R7 (hard rule): tenantId is NEVER accepted as a client-supplied
// argument. It is derived exclusively from `ctx.auth.getUserIdentity()`
// inside each handler. Every list/get filters on that derived tenantId via
// the `by_tenant` index (see convex/schema.ts).
//
// Convex API grounding: fetched 2026-07-12 via Context7 (`/llmstxt/convex_dev_llms-full_txt`).
// `query`/`mutation` builder shape, `ctx.db.insert/get/patch` (table name as
// first arg — current API per docs.convex.dev/production/multiple-repos and
// the 1.31.0 db.get/patch/replace/delete signature change), and
// `.withIndex(...)` all match current docs.

import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

/**
 * Derive the tenant id from the validated Convex auth identity.
 * Throws if there is no authenticated identity — every tenant-scoped
 * function must call this before touching the database.
 */
async function requireTenantId(ctx: { auth: { getUserIdentity: () => Promise<{ subject: string } | null> } }) {
  const identity = await ctx.auth.getUserIdentity();
  if (identity === null) {
    throw new Error("Unauthenticated: no valid identity on request");
  }
  // `subject` is the JWT `sub` claim — the stable per-user identifier Convex
  // Auth issues. This is the tenant id for the whole system (FOUNDATION_SLICE.md
  // §4: one user = one brand = one tenant for the foundation slice).
  return identity.subject;
}

export const createBrand = mutation({
  args: {
    name: v.string(),
    url: v.string(),
  },
  returns: v.id("brands"),
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);
    return await ctx.db.insert("brands", {
      tenantId,
      name: args.name,
      url: args.url,
      status: "provisioning",
      createdAt: Date.now(),
    });
  },
});

export const getBrand = query({
  args: {
    brandId: v.id("brands"),
  },
  returns: v.union(
    v.object({
      _id: v.id("brands"),
      _creationTime: v.number(),
      tenantId: v.string(),
      name: v.string(),
      url: v.string(),
      status: v.union(
        v.literal("provisioning"),
        v.literal("onboarding"),
        v.literal("active"),
        v.literal("archived"),
      ),
      createdAt: v.number(),
    }),
    v.null(),
  ),
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);
    const brand = await ctx.db.get("brands", args.brandId);
    if (brand === null) {
      return null;
    }
    // Never return a row that belongs to a different tenant, even by id
    // guess — the id alone must never be sufficient to read another
    // tenant's data (SPEC.md R2/R7).
    if (brand.tenantId !== tenantId) {
      return null;
    }
    return brand;
  },
});

export const listBrands = query({
  args: {},
  returns: v.array(
    v.object({
      _id: v.id("brands"),
      _creationTime: v.number(),
      tenantId: v.string(),
      name: v.string(),
      url: v.string(),
      status: v.union(
        v.literal("provisioning"),
        v.literal("onboarding"),
        v.literal("active"),
        v.literal("archived"),
      ),
      createdAt: v.number(),
    }),
  ),
  handler: async (ctx) => {
    const tenantId = await requireTenantId(ctx);
    return await ctx.db
      .query("brands")
      .withIndex("by_tenant", (q) => q.eq("tenantId", tenantId))
      .collect();
  },
});

export const updateBrandStatus = mutation({
  args: {
    brandId: v.id("brands"),
    status: v.union(
      v.literal("provisioning"),
      v.literal("onboarding"),
      v.literal("active"),
      v.literal("archived"),
    ),
  },
  returns: v.null(),
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);
    const brand = await ctx.db.get("brands", args.brandId);
    if (brand === null || brand.tenantId !== tenantId) {
      throw new Error("Brand not found for this tenant");
    }
    await ctx.db.patch("brands", args.brandId, { status: args.status });
    return null;
  },
});
