// convex/posts.ts
//
// Tenant-scoped mutation/query for the `posts` table -- generated content
// pieces produced by the Content Creator persona (kaizen/personas/
// content_creator.md). Mirrors convex/profile.ts's shape exactly:
// `createPost` is called by the FastAPI backend AFTER a content job
// completes (kaizen/api/routes_content.py reads content_latest.md that the
// worker wrote, then reconciles it back into Convex so the generated post
// stays durable + queryable), matching the same file-authoritative,
// Convex-durable-downstream pattern FOUNDATION_SLICE.md section 3
// establishes for brand DNA.
//
// SPEC.md R7: tenantId is derived from ctx.auth.getUserIdentity() only.
// FastAPI's service call to Convex must itself carry a Convex-verifiable
// identity, same caveat as convex/profile.ts's header comment.
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

const postStatus = v.union(
  v.literal("draft"),
  v.literal("scheduled"),
  v.literal("published"),
  v.literal("failed"),
);

const postObject = v.object({
  _id: v.id("posts"),
  _creationTime: v.number(),
  tenantId: v.string(),
  brandId: v.id("brands"),
  campaignId: v.optional(v.id("campaigns")),
  channel: v.string(),
  body: v.string(),
  mediaUrl: v.optional(v.string()),
  status: postStatus,
  publishedAt: v.optional(v.number()),
  createdAt: v.number(),
});

/**
 * Record a piece of Content-Creator-generated content as a draft post.
 * Called by the FastAPI backend after a content job completes -- the
 * worker writes the content to `content_latest.md` (file-authoritative
 * mid-run), then the backend reads it and reconciles it back into Convex
 * here, same file -> Convex reconciliation shape as
 * `profile:upsertBrandProfile`.
 */
export const createPost = mutation({
  args: {
    brandId: v.id("brands"),
    channel: v.string(),
    body: v.string(),
    campaignId: v.optional(v.id("campaigns")),
  },
  returns: v.id("posts"),
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);

    const brand = await ctx.db.get("brands", args.brandId);
    if (brand === null || brand.tenantId !== tenantId) {
      throw new Error("Brand not found for this tenant");
    }

    return await ctx.db.insert("posts", {
      tenantId,
      brandId: args.brandId,
      campaignId: args.campaignId,
      channel: args.channel,
      body: args.body,
      status: "draft",
      createdAt: Date.now(),
    });
  },
});

export const listPostsForBrand = query({
  args: {
    brandId: v.id("brands"),
  },
  returns: v.array(postObject),
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);

    return await ctx.db
      .query("posts")
      .withIndex("by_tenant_and_brand", (q) =>
        q.eq("tenantId", tenantId).eq("brandId", args.brandId),
      )
      .collect();
  },
});
