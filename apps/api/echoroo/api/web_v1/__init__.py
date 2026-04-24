"""First-party session API (Cookie + CSRF) under ``/web-api/v1/*``.

This package hosts endpoints that are callable only from the Echoroo
web UI (session cookie authentication, CSRF double-submit). The
programmatic API remains in :mod:`echoroo.api.v1` and uses Bearer API
keys.

Phase 2.4 adds the audit log read endpoints here (T056) but does NOT
wire the router into FastAPI's app factory — Phase 3 (T070+) takes
ownership of the middleware split and endpoint registration.
"""
