# ToriTore (とりトレ) Integration — Implementation Plan

> **Status**: Internal research preview only. **DO NOT merge to `main`.**
> Branch: `preview/toritore-integration` (cut from `main`).
> Must not conflict with `refactor/remove-annotation-project` — we only touch the
> **preserved** annotation-set side plus brand-new tables/files.

## 1. Goal

Integrate proficiency scores from NIES's bird-call learning app "とりトレ" (ToriTore)
into Echoroo's annotation workflow:

- **Part A — Participation gate**: A monitor can only annotate within an annotation set
  if their **latest ToriTore test `total_score` ≥ the set's threshold** (default 0.2).
- **Part B — Per-species proficiency snapshot**: When an annotation is created, snapshot
  the annotator's per-species correct rate onto the annotation row (simple version:
  average of `is_correct` across all of that user's stored tests; latest value if only one).

ToriTore has no API (CGI only) → users **upload the JSON** ToriTore exports.

## 2. Locked decisions

| Topic | Decision |
|---|---|
| Branch | New branch off `main`, preview-only, never merged to `main` |
| Gate scope | Per **annotation set** (`AnnotationSet.min_total_score`, default 0.2) |
| Upload UI | Requested **at annotation-set participation time** (gate panel on the set page) |
| Part B | **Simple version + snapshot** (store per-species rate on the annotation at creation) |

## 3. Input JSON shape (reconstructed)

```jsonc
{
  "timestamp": "20260604142325+9:00",
  "project": {
    "test_history": [
      {
        "test_timestamp": "1",
        "test_number": 1,
        "species_data": [
          { "species_name": "Hirundo rustica", "is_correct": 1, "species_id": "9515886" }
          // ... 26 species; species_id is a GBIF usageKey (numeric string)
        ],
        "total_score": 0.769230769230769
      }
    ],
    "project_name": "fukushima_bird",
    "project_id": "1",
    "user_id": "00004",
    "user_name": "yutea888"
  }
}
```

- `species_id` == GBIF usageKey → maps to `Taxon.gbif_taxon_key` (partial-unique index).
- `user_id` / `user_name` are **ToriTore-side** identifiers, NOT Echoroo users. The uploading
  Echoroo user is trusted to upload their own result (internal preview). Store ToriTore ids
  for reference only.

## 4. Assumptions (flag if wrong)

1. **Owners/Admins are exempt** from the participation gate (they run the study). Gate applies
   to Member/Viewer/Trusted principals.
2. `AnnotationSet.min_total_score` is **nullable**: `NULL` = no ToriTore requirement (gate skipped);
   a numeric value = required threshold. The set-settings UI prefills 0.2.
3. "Latest test" = across all of the user's uploaded tests, the most recent by
   (`source_timestamp` desc, `test_number` desc).
4. Per-species rate (simple) = `AVG(is_correct)` across all stored tests for that user + species,
   matched by `gbif_taxon_key`.

## 5. Data model (backend, Alembic migration `0025`)

### New tables

**`toritore_test_results`** — one row per test (a JSON's `test_history[]` expands to N rows)
- `id` UUID PK
- `user_id` UUID FK → users.id (the Echoroo uploader)
- `toritore_user_id` str, `toritore_user_name` str
- `toritore_project_id` str, `toritore_project_name` str
- `source_timestamp` datetime (parsed from top-level JSON `timestamp`)
- `test_number` int, `test_timestamp` str
- `total_score` float
- `uploaded_at` datetime (server default now)
- `raw_json` JSONB nullable (audit / reprocessing)
- Unique: `(user_id, source_timestamp, test_number)` — idempotent re-upload

**`toritore_species_scores`** — one row per species per test
- `id` UUID PK
- `test_result_id` UUID FK → toritore_test_results.id (CASCADE)
- `gbif_taxon_key` int
- `species_name` str
- `is_correct` smallint (0/1)
- `taxon_id` UUID FK → taxa.id (nullable; best-effort resolution by gbif key)
- Index on `(test_result_id)`, `(gbif_taxon_key)`

### Column additions (preserved models — safe vs. the removal refactor)

**`annotation_sets`**
- `min_total_score` float NULL (gate threshold; NULL = no requirement)

**`time_range_annotations`** (Part B snapshot, all nullable)
- `annotator_species_score` float NULL
- `annotator_total_score` float NULL
- `annotator_test_reference` str NULL  (e.g. `"test#1@20260604142325+9:00"`)

## 6. Backend services / endpoints

### Parser/service: `services/toritore.py` (new)
- `ingest_upload(user_id, payload) -> ProficiencySummary` — validate JSON, expand test_history,
  resolve each species by `gbif_taxon_key` (best-effort), upsert rows (idempotent).
- `get_latest_total_score(user_id) -> float | None`
- `get_species_rate(user_id, gbif_taxon_key) -> float | None` (simple AVG)
- `get_summary(user_id) -> {latest_total_score, tests, per_species_rates}`

### BFF (`/web-api/v1`) — user-self-scoped (USER_SCOPED_ONLY allowlist pattern, like spec/011 me.py)
- `POST /web-api/v1/me/toritore-results` — upload JSON (multipart or application/json) → ingest → summary
- `GET  /web-api/v1/me/toritore-results` — current proficiency summary
- `GET  /web-api/v1/projects/{pid}/annotation-sets/{sid}/eligibility`
  → `{ required: float|null, my_latest_total_score: float|null, eligible: bool, is_exempt: bool }`

### Gate + snapshot integration (existing preserved path)
- In `services/annotation_segment.py` create-annotation flow:
  1. Load segment → annotation set → `min_total_score`.
  2. If threshold set AND user not Owner/Admin: require `latest_total_score >= min_total_score`,
     else raise 403 `toritore_score_insufficient` (with `{required, current}` detail).
  3. On success, compute `annotator_species_score` (by the annotated taxon's gbif key),
     `annotator_total_score`, `annotator_test_reference`; persist on the row.
- Annotation-set create/update schema + service: accept/return `min_total_score`.

## 7. Frontend (SvelteKit, `apps/web`)

- **Set page** `(app)/projects/[id]/annotation-sets/[setId]`: on load, call `eligibility`.
  If not eligible → render a **gate panel** instead of (or overlaying) the annotation editor:
  - Explanation + required score + current status ("未提出" / "最新総合点: Y").
  - ToriTore JSON file upload → `POST /me/toritore-results` → re-fetch eligibility → unlock.
- **Set settings**: numeric input for `min_total_score` (prefill 0.2; clearable = no requirement).
- New API client `lib/api/me-toritore.ts` (reuse shared `callWebApi` Bearer+CSRF helper).
- i18n keys in `messages/en.json` + `ja.json`.

## 8. Species resolution detail

- For each `species_data` entry: `Taxon.get_by_gbif_taxon_key(int(species_id))`.
  - Found → set `taxon_id`. Not found → store `gbif_taxon_key` + `species_name` only.
- Snapshot match at annotation time is by **`gbif_taxon_key`** (annotated taxon → its gbif key →
  AVG over user's species_scores). Robust even if taxon_id wasn't resolved at upload time.

## 9. Verification (CLAUDE.md 完了の定義)

- **Gate 1**: `npm run check`, `uv run mypy .`, `uv run ruff check .`
- **Gate 2**: pytest via `docker exec echoroo-backend ... --no-cov` (host pytest blocked); `npm run test`
- **Gate 3 (browser, dev env, TEST_MODE on, shared TOTP, test@echoroo.app)**:
  1. Open a set with `min_total_score=0.2` as a non-admin monitor → see gate panel.
  2. Upload sample JSON (total_score 0.769) → unlock.
  3. Create an annotation → verify snapshot fields populated.
  4. Lower-score JSON / no upload → gate blocks (403 path) with clear message.
  5. Console error count == 0.

## 10. Build sequence

1. Branch `preview/toritore-integration` from `main`.
2. Backend: models + migration 0025 → `services/toritore.py` → schema fields → BFF endpoints
   → gate + snapshot in annotation_segment flow. (backend-developer / Codex)
3. Frontend: eligibility + gate panel + upload + set-settings field + i18n. (frontend-developer / Codex)
4. Tests (test-automator) → type/lint/pytest → Playwright Gate 3.
5. Review (code-reviewer / Codex). Keep on the preview branch; no main PR.

## 11. Implementation status — DONE (2026-06-08, branch `preview/toritore-integration`, uncommitted)

All four locked decisions implemented; all gates green.

- **Gate 1 (static)**: backend mypy + ruff clean (in-container); frontend `npm run check` 0 errors (17 pre-existing warnings).
- **Gate 2 (unit)**: ToriTore backend tests 19 passed (parser/idempotency/queries/gate/snapshot + is_correct clamp + legacy-path gate).
- **Gate 3 (browser, dev, TEST_MODE toggled on→reverted)**: all 5 parts PASS — settings UI persists `min_total_score=0.2`; gate panel renders for monitor (`e2e-member`); low score (0.115) blocked; passing score (0.769) unlocks editor; real annotation created with snapshot `annotator_total_score≈0.769`, `annotator_test_reference=test#1@2026-06-04T05:23:25+00:00` (`annotator_species_score` NULL — sample GBIF key not in dev taxa, by-design). Console errors 0. TEST_MODE confirmed back to `false`.
- Migration `0025` applied to the DEV DB (not main/CI).

### Review outcome (code-reviewer) + resolutions
- **H1 (fixed)**: the gate is now enforced **server-side and unconditionally** — `services/annotation_segment.py::create_annotation` resolves the owning project from `segment → AnnotationSet.project_id` when no `project_id` is passed, so the legacy `/api/v1/segments/{id}/annotations` path can no longer bypass it. BFF happy path unchanged.
- **M2 (fixed)**: `is_correct` normalized strictly to {0,1} (Pydantic validator + persistence guard).
- **M4 (fixed)**: redundant mid-request `db.commit()` removed from `ingest_upload`.
- **M3 (accepted, by-design)**: `total_score` is fully user-controlled (the export is user-uploaded, ToriTore has no API/signature). The gate is **not tamper-resistant** — acceptable for an internal trusted-monitor preview. Do NOT treat as a security control. If it ever graduates beyond preview, bind to a signed export or a server-side test session.
- **M5 (accepted, low risk)**: the `(user_id, source_timestamp, test_number)` unique constraint does not dedup rows whose `source_timestamp` is NULL (unparseable timestamp); single-request idempotency is handled in the service. Revisit only if concurrent uploads with unparseable timestamps become a real case.
- **Out of scope (pre-existing, spec/009)**: the legacy `/api/v1/segments/*` router lacks project-membership authorization entirely; the H1 fix closes the ToriTore-gate bypass but not the broader spec/009 legacy-auth gap (tracked elsewhere, not part of this preview feature).

### Notes for whoever resumes
- Branch is **uncommitted** (modified + untracked files). Do NOT merge to `main`.
- Dev test data used: project `5673b55a-…`, set `359a0c3d-…` ("A3 Gate3 ja-vernacular check"), monitor `e2e-member@echoroo.app`. Sample uploads at `/tmp/toritore_pass.json` / `/tmp/toritore_fail.json` (regenerate from §3 if gone).
- Per-species refined formula (§1 "精緻版": average over tests after the target was first reached) is deferred; all per-test species results are persisted so it can be added later as a query/computation change only (no migration).
