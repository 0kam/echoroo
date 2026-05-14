# Phase 1 — Data Model

**Date**: 2026-05-12
**Spec**: [spec.md](spec.md)
**Plan**: [plan.md](plan.md)

## Scope

This feature is a **transport-and-routing migration** between two already-existing HTTP surfaces (`/api/v1/*` and `/web-api/v1/*`). It introduces **no new domain entities, no schema changes, and no new persistence**.

The plan template asks for a data-model section anyway; this file exists to make the absence of schema work explicit and to call out the few existing entities the migration touches read-only.

## Entities (existing — exposed through a new transport, reusing existing service transitions)

The BFF adapters added in this migration expose existing entities through a new HTTP surface. **No new entities, no new fields, no new state transitions, no schema changes.** Mutations (e.g. admin license create, project update from PR A2) reuse the same service-layer functions and the same state transitions that the legacy `/api/v1/*` paths already use.

| Entity | Owner | Read on BFF | Mutation on BFF | Notes |
|--------|-------|-------------|-----------------|-------|
| `User` | `apps/api/echoroo/models/user.py` | Yes (`web_v1/users.py:54`, every adapter's `CurrentUser`) | No (profile mutations stay on legacy — documented exception) | — |
| `Project` | `apps/api/echoroo/models/project.py` | Existing BFF reads (`web_v1/projects/_core.py`): list, detail, recordings. **PR A2 adds**: members listing, overview reads. | **PR A2 adds**: create, update, delete, member CRUD — reuses `ProjectService` transitions | The legacy `/api/v1/projects/{id}/members` and `/api/v1/projects/{id}/overview` reads have no BFF mirror at the start of this migration; PR A2 introduces them alongside mutations so the resource family ships its full BFF surface in one bridge PR. |
| `Recorder` | `apps/api/echoroo/models/recorder.py` | New BFF in PR F | Yes — reuses `services/admin/recorders.py` transitions | — |
| `License` | `apps/api/echoroo/models/license.py` | New BFF in PR E | Yes — reuses `services/admin/licenses.py` transitions | — |
| `SystemSetting` (or equivalent) | `services/admin/settings.py` | New BFF in PR G | Yes — reuses the same setter transitions | — |
| `Taxon` / `GbifSpecies` | `services/taxa.py` | New BFF in PR C | No (search + lookup are read-only) | — |
| `ApiKey` | `apps/api/echoroo/models/api_key.py` | **Not** touched | **Not** touched | Mentioned only to clarify it is the legacy `/api/v1/*` auth identity, deliberately isolated from the BFF surface. |

## State transitions

This feature introduces **no new state transitions**. The existing transitions defined by each service-layer module remain authoritative. When a mutation arrives via a new BFF adapter (PR A2 or PRs E–H), it delegates to the same service-layer function the legacy `/api/v1/*` handler would have called. The transport changes; the transition does not.

## Relationships

Unchanged. All foreign keys, joins, and constraints remain as defined by the existing schema.

## Validation rules

Unchanged. The Pydantic request/response schemas used by each new BFF adapter are **the same schemas** the legacy v1 router uses, ensuring identical validation surface area.

## Why this file is short

A non-empty data-model.md in a routing-only migration would invite drift. The actual source of truth for these entities lives in the SQLAlchemy models and Pydantic schemas already in the repo. Listing fields here would duplicate them and immediately decay.

If a future PR in this sequence discovers it needs a new field (e.g. an audit-attribute on `License` to record who flipped a flag from the BFF surface), that PR's plan addendum — not this file — is the correct place to document it.
