// Tenant-scoped queries for eval runs.

import { query } from "./_generated/server";
import { v } from "convex/values";

async function requireTenantId(ctx: { auth: { getUserIdentity: () => Promise<{ subject: string } | null> } }) {
  const identity = await ctx.auth.getUserIdentity();
  if (identity === null) {
    throw new Error("Unauthenticated: no valid identity on request");
  }
  return identity.subject;
}

const evalRunObject = v.object({
  _id: v.id("eval_runs"),
  _creationTime: v.number(),
  tenantId: v.string(),
  brandId: v.id("brands"),
  postId: v.id("posts"),
  predictedScore: v.optional(v.number()),
  actualScore: v.optional(v.number()),
  rationale: v.optional(v.string()),
  createdAt: v.number(),
});

export const listEvalRuns = query({
  args: {},
  returns: v.array(evalRunObject),
  handler: async (ctx) => {
    const tenantId = await requireTenantId(ctx);
    return await ctx.db
      .query("eval_runs")
      .withIndex("by_tenant", (q) => q.eq("tenantId", tenantId))
      .collect();
  },
});

export const getEvalRun = query({
  args: {
    runId: v.id("eval_runs"),
  },
  returns: v.union(evalRunObject, v.null()),
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);
    const run = await ctx.db.get("eval_runs", args.runId);
    if (run === null || run.tenantId !== tenantId) {
      return null;
    }
    return run;
  },
});
