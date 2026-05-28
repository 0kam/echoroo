# Data Model: License Master Unification

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md) | **Date**: 2026-05-26

This document describes the entities involved in the feature, the schema changes the migration applies,
the relationships between entities, and the validation rules each entity carries. Storage details
(PostgreSQL types, FK constraints, indexes) are included because they materially affect the migration
and the runtime semantics of the feature.

---

## Entities

### License (existing)

The master table of acceptable project and dataset licenses. Owned and curated by platform administrators.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `VARCHAR(50)` | PK, NOT NULL | Stable identifier. Human-meaningful (e.g. `cc0`, `cc-by`); does not change on rename. |
| `short_name` | `VARCHAR(50)` | NOT NULL, **NEW unique constraint** | Display label in dropdowns. Indexed for `ORDER BY short_name` on the list endpoint. |
| `name` | `VARCHAR(200)` | NOT NULL | Full human-readable name (e.g. "Creative Commons Attribution 4.0 International"). |
| `url` | `VARCHAR(500)` | NULL | Canonical URL to the license text. |
| `description` | `TEXT` | NULL | Optional admin-authored note. |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | Set by ORM / migration. |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | Maintained by `onupdate` in the model. |

**New constraint added by this feature**: `UNIQUE(short_name)`. The existing table has no unique constraint on short_name, but as the field is what users see and select by, two entries with the same `short_name` would silently corrupt the dropdown UX (the second would override the first in display). Idempotent if the pre-feature data happens to already have unique short_names (which the seeded data does).

**Seed rows added by the migration** (each row inserted with `INSERT ... ON CONFLICT (id) DO NOTHING` so an existing admin-curated master is never overwritten):

| id | short_name | name | url | description |
|---|---|---|---|---|
| `cc0` | `CC0` | Creative Commons Zero 1.0 Universal (Public Domain Dedication) | `https://creativecommons.org/publicdomain/zero/1.0/` | No rights reserved. |
| `cc-by` | `CC-BY` | Creative Commons Attribution 4.0 International | `https://creativecommons.org/licenses/by/4.0/` | Attribution required. |
| `cc-by-nc` | `CC-BY-NC` | Creative Commons Attribution-NonCommercial 4.0 International | `https://creativecommons.org/licenses/by-nc/4.0/` | Attribution, non-commercial use only. |
| `cc-by-sa` | `CC-BY-SA` | Creative Commons Attribution-ShareAlike 4.0 International | `https://creativecommons.org/licenses/by-sa/4.0/` | Attribution, share-alike. |

The mapping from the legacy `ProjectLicense` enum strings to the seeded `id` values is deterministic per FR-009. Stored as a constant `_LICENSE_ID_FOR_ENUM` in the migration file so future operators can audit it.

### Project (modified)

Existing entity. This feature changes only the license relationship; all other fields and behaviors are unchanged.

| Column | Type | Constraints | Change in this feature |
|---|---|---|---|
| `license` | `VARCHAR(...)` (enum string) | NULL | **DROPPED after data migration** |
| `license_id` | `VARCHAR(50)` | NULL, **NEW FK to `licenses(id)` ON DELETE RESTRICT** + **NEW index `ix_projects_license_id`** | New column. Populated from the legacy `license` value via the deterministic map in the same migration. |

Behavior:
- A project may have `license_id IS NULL` **only as a legacy state** preserved from pre-migration rows that had `license IS NULL`. New project creation requires a license (FR-005, aligning with spec/006); no application code path produces a NULL `license_id` after this feature ships.
- A project's `license_id` MUST reference an existing row in `licenses`. Enforced by the FK; the application validates the submitted `license_id` exists in the master at create/update time so a 422 with `error_code: "license_not_found"` is surfaced before the FK error.
- The API request field for create/update is `license_id: str` (the stable FK identifier). The API response field `project.license` continues to exist with type `str | None`, populated by joining `licenses.short_name` (R1, no breaking change on the response side).

### ProjectLicenseHistory (modified — column type change only)

Existing entity (Phase 7 / FR-086 + FR-087). Tracks every license transition on a project; rendered by the FR-087 license-history surface and reflected in the FR-086 CSV export. This feature converts the two enum-typed columns to plain VARCHAR strings so admin-added license values can flow through the history without crashing the insert path.

| Column | Type | Constraints | Change in this feature |
|---|---|---|---|
| `old_license` | `ProjectLicense` enum | NULL | **TYPE CHANGED to VARCHAR(50)** via `ALTER COLUMN ... USING old_license::text`. Snapshot value preserved verbatim. |
| `new_license` | `ProjectLicense` enum | NOT NULL | **TYPE CHANGED to VARCHAR(50)** via the same pattern. |

Behavior:
- History rows are immutable snapshots (FR-005a). Subsequent admin renames of `licenses.short_name` do NOT rewrite history; this is intentional and documented.
- No FK relationship is added between `project_license_history` and `licenses` — see R8.

### Dataset (modified constraint only)

Existing entity. The column `license_id` is unchanged; only the FK constraint's ON DELETE behavior changes.

| Column | Type | Constraints | Change in this feature |
|---|---|---|---|
| `license_id` | `VARCHAR(50)` | NULL, **FK to `licenses(id)` — was ON DELETE SET NULL, BECOMES ON DELETE RESTRICT** | Constraint replaced in same migration (FR-013). |

Behavior:
- Existing dataset rows keep their `license_id` values verbatim. No data migration on this side.
- Attempting to delete a license still referenced by any dataset now refuses (was: silently set the dataset's `license_id` to NULL on delete).

---

## Relationships

```
licenses (1) ────── (0..N) projects     [project.license_id]
   │
   └─────────── (0..N) datasets         [dataset.license_id]
```

Both relationships are many-to-one (each project / dataset has at most one license; each license can be referenced by many projects and many datasets).

Both relationships use the same FK behavior after this feature: **ON DELETE RESTRICT**.

There is no direct project ↔ dataset license coupling. A project and a dataset attached to that project may legitimately have different licenses (e.g. a research project licensed CC-BY publishing a dataset under CC0). This feature does not introduce any constraint between project license and dataset license.

---

## Schema-change summary (one Alembic migration: 0024 unless other migrations land first)

Reordered after Codex review to put the audit step **first** so that an abort happens before any irreversible structural change is committed (R4 revised).

```text
1. AUDIT — FR-010 safety belt (runs BEFORE any schema or seed change).
   For each of (projects.license, project_license_history.old_license,
   project_license_history.new_license):
     SELECT DISTINCT <col> FROM <table>
     WHERE <col> IS NOT NULL
     AND <col> NOT IN ('CC0','CC-BY','CC-BY-NC','CC-BY-SA')
   If any of the three queries returns rows, raise ValueError with the
   offending values; Postgres rolls back the transaction immediately
   (no schema mutation has occurred yet).

2. Add UNIQUE constraint on licenses.short_name
   (idempotent — the seeded short_names are already unique).
   This MUST land before the seed (step 3) so that ON CONFLICT (short_name)
   in step 3 has a constraint to honour.

3. INSERT ... ON CONFLICT (short_name) DO NOTHING for the four canonical
   seed rows. Using short_name (not id) as the conflict target honours
   FR-007 "the seed must only fill in rows whose short_name is not
   already present — never overwrite admin edits"; an admin-curated
   "CC0" with id='public-domain' is preserved untouched.

4. ADD COLUMN projects.license_id VARCHAR(50) NULL
   (FK constraint added separately in step 6 for safe transactional
   rollback; the index is created alongside the FK in step 6).

5. UPDATE projects SET license_id = CASE license
     WHEN 'CC0'      THEN 'cc0'
     WHEN 'CC-BY'    THEN 'cc-by'
     WHEN 'CC-BY-NC' THEN 'cc-by-nc'
     WHEN 'CC-BY-SA' THEN 'cc-by-sa'
   END
   WHERE license IS NOT NULL.
   Pre-existing rows with license IS NULL get license_id IS NULL
   (FR-005 — preserved as legacy).

6. ADD CONSTRAINT projects_license_id_fkey FOREIGN KEY (license_id)
     REFERENCES licenses(id) ON DELETE RESTRICT;
   CREATE INDEX ix_projects_license_id ON projects(license_id);

7. DROP COLUMN projects.license.

8. ALTER project_license_history.old_license TYPE VARCHAR(50)
     USING old_license::text;
   ALTER project_license_history.new_license TYPE VARCHAR(50)
     USING new_license::text.
   (FR-005a + R8 — history columns become snapshot strings, NOT
   FK-referenced.)

9. DROP CONSTRAINT datasets_license_id_fkey;
   ADD CONSTRAINT datasets_license_id_fkey FOREIGN KEY (license_id)
     REFERENCES licenses(id) ON DELETE RESTRICT.
   (Constraint name to be pulled from actual schema at implementation
   time; placeholder above.)

10. downgrade(): raise NotImplementedError("forward-only migration;
    see spec/011 step 11 precedent").

NOTE on the legacy ``projectlicense`` Postgres enum type: it is left
in place after migration. Dropping it requires verifying no other
column references it, which is deferred to a follow-up cleanup
migration once spec/012 is in production.
```

All schema-modifying steps (2–9) run in a single transaction; any failure (including the FR-010 abort at step 1) rolls back the entire migration. No partial state can be left behind.

---

## Validation rules

| Rule | Layer | Description |
|---|---|---|
| `licenses.short_name` non-empty | DB + Pydantic | Existing `NOT NULL`; Pydantic schema rejects empty strings. |
| `licenses.short_name` unique | DB | New unique constraint added by migration. |
| `licenses.id` ≤ 50 chars | DB | Existing column type. Backend validates incoming creation requests against this length. |
| `projects.license_id` references existing license | DB (FK) + service | FK enforces at insert/update; service layer pre-validates incoming `license` short_name and translates to `license_id`, returning 400 with a useful message if unknown. |
| License delete refused when in use | DB (FK ON DELETE RESTRICT) + service | Service computes dependent counts and returns 409 Conflict with counts before the FK error fires; FK is the safety net for race conditions. |

---

## State transitions

None material. The `licenses` table has no lifecycle states — rows are created, updated, deleted as discrete operations. Projects and datasets do not change license-related lifecycle as part of this feature.

---

## Indexes

- `licenses (id)` — already indexed (PK).
- `licenses (short_name)` — **NEW** unique index, created by the unique constraint added in step 1 of the migration.
- `projects (license_id)` — **NEW** index (auto-created by FK in step 6 on some backends; explicitly added for clarity / safety on PostgreSQL).
- `datasets (license_id)` — already indexed (FK created originally).

Other indexes on the affected tables are unchanged.

---

## Backward compatibility

- **API responses**: `project.license` remains a `str | None` field with the same wire shape as today. Callers that read `project.license == "CC-BY"` continue to work unchanged after the migration (the new code path joins the master and returns the same string).
- **API requests**: `POST /projects` continues to accept `license: str | None` (the short_name). Backend now resolves it to `license_id` server-side before insert. Unknown short_names yield a 422 with a friendly message (was: enum validation failure with a different message).
- **Direct DB consumers (if any)**: Any external tool reading `projects.license` directly will break (column is dropped). The pre-launch project status documented in memory makes this acceptable; no external consumers are known to exist.

---

## Anti-corruption notes

- The deterministic mapping table from legacy enum string to seeded `id` is hardcoded in the migration. If the seeded rows are later renamed by an admin, the migration's mapping is still correct (it points at `id`, not `short_name`).
- The seed step is idempotent (`ON CONFLICT DO NOTHING`); re-running the migration on a database that already has the four rows is a no-op for the seed step. The schema-modifying steps (4, 6, 7, 8) are not idempotent on their own — Alembic's revision tracking is the safety belt that prevents them from being re-run.
