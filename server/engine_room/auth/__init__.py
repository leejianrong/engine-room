"""Human authentication (ADR-0013) — GitHub OAuth via FastAPI-Users.

Modular/provider-agnostic per ADR-0013: the User model, auth backend, and
session strategy are provider-independent, so Google/password backends can be
added later without rework. V2 (slice A2) wires GitHub OAuth + a stateless JWT
session (D-l).
"""
