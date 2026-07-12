// convex/jobs.ts
//
// Tenant-scoped queries/mutations for the `jobs` table — the async job model
// shared by FastAPI (`{job_id, tenant_id, type, status, events[]}`, SPEC.md
// §5) and the frontend's job/eval panel (FOUNDATION_SLICE.md §6a streaming
// architecture: FastAPI owns the live event stream over SSE; Convex is the
// durable job status record the frontend can also subscribe to).
//
// SPEC.md R7: tenantId is derived from ctx.auth.getUserIdentity() only,
// never a client-supplied argument.
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

const jobStatus = v.union(
  v.literal("queued"),
  v.literal("running"),
  v.literal("done"),
  v.literal("failed"),
);

const jobObject = v.object({
  _id: v.id("jobs"),
  _creationTime: v.number(),
  jobId: v.string(),
  tenantId: v.string(),
  brandId: v.optional(v.id("brands")),
  type: v.string(),
  status: jobStatus,
  error: v.optional(v.string()),
  result: v.optional(v.any()),
  createdAt: v.number(),
  updatedAt: v.number(),
});

export const createJob = mutation({
  args: {
    jobId: v.string(),
    type: v.string(),
    brandId: v.optional(v.id("brands")),
  },
  returns: v.id("jobs"),
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);

    if (args.brandId !== undefined) {
      const brand = await ctx.db.get("brands", args.brandId);
      if (brand === null || brand.tenantId !== tenantId) {
        throw new Error("Brand not found for this tenant");
      }
    }

    const now = Date.now();
    return await ctx.db.insert("jobs", {
      jobId: args.jobId,
      tenantId,
      brandId: args.brandId,
      type: args.type,
      status: "queued",
      createdAt: now,
      updatedAt: now,
    });
  },
});

export const updateJobStatus = mutation({
  args: {
    jobId: v.string(),
    status: jobStatus,
    error: v.optional(v.string()),
    result: v.optional(v.any()),
  },
  returns: v.null(),
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);

    const job = await ctx.db
      .query("jobs")
      .withIndex("by_jobId", (q) => q.eq("jobId", args.jobId))
      .unique();

    if (job === null || job.tenantId !== tenantId) {
      throw new Error("Job not found for this tenant");
    }

    await ctx.db.patch("jobs", job._id, {
      status: args.status,
      error: args.error,
      result: args.result,
      updatedAt: Date.now(),
    });
    return null;
  },
});

export const getJob = query({
  args: {
    jobId: v.string(),
  },
  returns: v.union(jobObject, v.null()),
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);

    const job = await ctx.db
      .query("jobs")
      .withIndex("by_jobId", (q) => q.eq("jobId", args.jobId))
      .unique();

    if (job === null || job.tenantId !== tenantId) {
      return null;
    }
    return job;
  },
});

export const listJobsForBrand = query({
  args: {
    brandId: v.id("brands"),
  },
  returns: v.array(jobObject),
  handler: async (ctx, args) => {
    const tenantId = await requireTenantId(ctx);

    const brand = await ctx.db.get("brands", args.brandId);
    if (brand === null || brand.tenantId !== tenantId) {
      return [];
    }

    return await ctx.db
      .query("jobs")
      .withIndex("by_tenant_and_brand", (q) =>
        q.eq("tenantId", tenantId).eq("brandId", args.brandId),
      )
      .collect();
  },
});

export const listJobs = query({
  args: {},
  returns: v.array(jobObject),
  handler: async (ctx) => {
    const tenantId = await requireTenantId(ctx);

    return await ctx.db
      .query("jobs")
      .withIndex("by_tenant", (q) => q.eq("tenantId", tenantId))
      .collect();
  },
});
