"""Kaizen FastAPI control plane: auth boundary, tenant routing, job queue,
and SSE streaming in front of the per-tenant Hermes worker pool.

Nothing in this package trusts a client-supplied tenant/brand id as
identity (SPEC.md R7) -- ``deps.require_tenant`` is the only path by which a
route learns ``tenant_id``, and it is always derived from a validated Convex
Auth JWT (``kaizen.auth.verify_convex_jwt``).
"""
