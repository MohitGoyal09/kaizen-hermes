// Tenant-scoped queries for channel engagement metrics.

import { query } from "./_generated/server";
import { v } from "convex/values";

async function requireTenantId(ctx: { auth: { getUserIdentity: () => Promise<{ subject: string } | null> } }) {
  const identity = await ctx.auth.getUserIdentity();
  if (identity === null) {
    throw new Error("Unauthenticated: no valid identity on request");
  }
  return identity.subject;
}

const engagementObject = v.object({
  _id: v.id("engagement"),
  _creationTime: v.number(),
  tenantId: v.string(),
  brandId: v.id("brands"),
  postId: v.id("posts"),
  channel: v.string(),
  likes: v.optional(v.number()),
  shares: v.optional(v.number()),
  comments: v.optional(v.number()),
  impressions: v.optional(v.number()),
  fetchedAt: v.number(),
});

export const listEngagement = query({
  args: {},
  returns: v.array(engagementObject),
  handler: async (ctx) => {
    const tenantId = await requireTenantId(ctx);
    return await ctx.db
      .query("engagement")
      .withIndex("by_tenant", (q) => q.eq("tenantId", tenantId))
      .collect();
  },
});
