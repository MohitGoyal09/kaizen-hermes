// Tenant-scoped queries/mutations for campaigns.
//
// tenantId is always derived from Convex Auth identity, never from args.

import { mutation, query } from "./_generated/server";
import { v } from "convex/values";

async function requireTenantId(ctx: { auth: { getUserIdentity: () => Promise<{ subject: string } | null> } }) {
  const identity = await ctx.auth.getUserIdentity();
  if (identity === null) {
    throw new Error("Unauthenticated: no valid identity on request");
  }
  return identity.subject;
}

const campaignStatus = v.union(
  v.literal("draft"),
  v.literal("active"),
  v.literal("completed"),
  v.literal("archived"),
);

const campaignObject = v.object({
  _id: v.id("campaigns"),
  _creationTime: v.number(),
  tenantId: v.string(),
  brandId: v.id("brands"),
  name: v.string(),
  goal: v.optional(v.string()),
  channels: v.optional(v.array(v.string())),
  formats: v.optional(v.array(v.string())),
  summary: v.optional(v.string()),
  status: campaignStatus,
  createdAt: v.number(),
  updatedAt: v.optional(v.number()),
});

export const createCampaign = mutation({
  args: {
    brandId: v.id("brands"),
    name: v.string(),
    goal: v.optional(v.string()),
    channels: v.optional(v.array(v.string())),
    formats: v.optional(v.array(v.string())),
    status: v.optional(campaignStatus),
  },
  returns: campaignObject,
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);

    const brand = await ctx.db.get("brands", args.brandId);
    if (brand === null || brand.tenantId !== tenantId) {
      throw new Error("Brand not found for this tenant");
    }

    const campaignId = await ctx.db.insert("campaigns", {
      tenantId,
      brandId: args.brandId,
      name: args.name,
      goal: args.goal,
      channels: args.channels ?? [],
      formats: args.formats ?? [],
      summary: args.goal,
      status: args.status ?? "draft",
      createdAt: Date.now(),
      updatedAt: Date.now(),
    });

    const campaign = await ctx.db.get(campaignId);
    if (campaign === null) {
      throw new Error("Campaign insert failed");
    }
    return campaign;
  },
});

export const listCampaigns = query({
  args: {},
  returns: v.array(campaignObject),
  handler: async (ctx) => {
    const tenantId = await requireTenantId(ctx);
    return await ctx.db
      .query("campaigns")
      .withIndex("by_tenant", (q) => q.eq("tenantId", tenantId))
      .collect();
  },
});

export const getCampaign = query({
  args: {
    campaignId: v.id("campaigns"),
  },
  returns: v.union(campaignObject, v.null()),
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);
    const campaign = await ctx.db.get("campaigns", args.campaignId);
    if (campaign === null || campaign.tenantId !== tenantId) {
      return null;
    }
    return campaign;
  },
});
