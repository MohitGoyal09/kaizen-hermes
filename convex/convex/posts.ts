// convex/posts.ts
//
// Tenant-scoped mutation/query for the `posts` table. Content jobs create
// durable post rows through `createPost`; dashboard/API consumers read them
// through tenant-scoped list queries.

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

    if (args.campaignId !== undefined) {
      const campaign = await ctx.db.get("campaigns", args.campaignId);
      if (campaign === null || campaign.tenantId !== tenantId) {
        throw new Error("Campaign not found for this tenant");
      }
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

export const listPosts = query({
  args: {
    campaignId: v.optional(v.id("campaigns")),
  },
  returns: v.array(postObject),
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);

    if (args.campaignId !== undefined) {
      const campaign = await ctx.db.get("campaigns", args.campaignId);
      if (campaign === null || campaign.tenantId !== tenantId) {
        return [];
      }

      return await ctx.db
        .query("posts")
        .withIndex("by_tenant_and_campaign", (q) =>
          q.eq("tenantId", tenantId).eq("campaignId", args.campaignId),
        )
        .collect();
    }

    return await ctx.db
      .query("posts")
      .withIndex("by_tenant", (q) => q.eq("tenantId", tenantId))
      .collect();
  },
});
