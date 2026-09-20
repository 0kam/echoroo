# Storage migration: LocalStack S3 to Lustre POSIX

Status: reviewed (2026-09-20) — slice 3 blocked on open decision 1

## Decision

Drop the S3 object-storage layer and read/write recordings, model artifacts and
search reference audio directly on the Lustre filesystem mounted at `/data`.
Replace the implementation behind `core/s3.py` in place; do not introduce a
storage abstraction with two backends.

## Context

- The only S3 implementation in use is LocalStack, pinned to
  `localstack/localstack:community-archive` — the final token-free build, no
  further updates (`compose.dev.yaml:69-76`). There is no production compose
  file, so some migration is mandatory before launch.
- The usual drop-in replacement is gone: MinIO removed the community admin UI
  in 2025 and archived its repository in April 2026. Garage, SeaweedFS or Ceph
  RGW would mean operating a distributed object store for a benefit Lustre
  already provides.
- The VM has a 20 TiB Lustre filesystem at `/data`: POSIX, writable, reachable
  from several VMs in the project, GPU available. The mount options cannot be
  changed by us.
- Echoroo has not launched. There is no data to migrate and no compatibility
  window.
- `Recording.path` is written as the S3 key and is also interpreted relative to
  `AUDIO_ROOT` (`workers/upload_tasks.py:215`, `:739`). The data model needs no
  change.
- Reads resolve local paths in two places, not one:
  `AudioService.ensure_file_local()` (`services/audio/service.py:138`, the S3
  download gate) and `get_absolute_path()` (`:103`), which `read_audio()`
  (`:296`) and `load_clip_bytes()` (`:691`) call directly. Both look under
  `AUDIO_ROOT` first, so both resolve once Lustre is `AUDIO_ROOT`.
- The API and the Celery workers already share a POSIX volume
  (`backend-data:/data`).
- No multipart upload is used anywhere. Spectrograms and export artifacts never
  touch S3.
- S3 server-side encryption is not used. LocalStack KMS backs TOTP envelope
  encryption, PII HMAC, the audit chain hash and invitation token signing —
  unrelated to object storage.

Persistent namespaces that must all move: `recordings/`, `uploads/` (staging),
`search_reference/{project}/{job}` (`api/v1/search/batch.py:226`, `:342`,
`models/search_session.py:124`), `models/{project}/{model}/model.joblib`
(`workers/classifier/training.py:360`, `workers/classifier/utils.py:243`),
`audit-log/`.

## Data placement

| Location | Contents |
| --- | --- |
| Lustre `/data` | Recording originals, model artifacts, search reference audio |
| Local disk | PostgreSQL data directory, Redis dump, Docker volumes, spectrogram and OGG playback caches |

Lustre is built for large sequential I/O; its metadata server is the bottleneck
for files under ~256 KiB. PostgreSQL and Redis never go on Lustre.

The OGG playback cache is currently hardcoded to `/data/audio_compressed`
(`services/audio/service.py:576`), which on the VM is Lustre. It must become a
setting pointing at local disk (slice 4).

## Assumptions

- **No cluster-wide locking is needed from the mount.** The application never
  calls `flock`, and PostgreSQL is not on Lustre. Reversible: would surface as
  lock errors in worker logs.
- **Default Lustre striping is adequate for 30-minute WAV files.** Reversible:
  `lfs setstripe` on the recordings directory if throughput disappoints.
- **One VM first.** Splitting the GPU worker onto a second VM later needs only
  the same `/data` mount; nothing in this design depends on it.
- **POSIX copies take a fresh mtime** (`shutil.copyfile`, not `copy2`). The
  search reference janitor filters orphans by age
  (`core/s3.py:334`, `workers/search_tasks.py:806-821`); a preserved mtime
  would make a new copy look like an old orphan.

## Open decisions

| # | Question | Options (recommended first) | Consequence | Blocks |
| --- | --- | --- | --- | --- |
| 1 | How must audit log archives stay immutable once S3 Object Lock is gone? | (a) KMS chain hash for tamper evidence + read-only mount and snapshots for immutability; (b) ship archives to an external append-only store | (a) no new infrastructure, immutability is operational rather than enforced; (b) enforced WORM, one more system to run | slice 3, therefore slice 4 |
| 2 | How much local (non-Lustre) disk does the VM have? | — (fact needed) | Sizes PostgreSQL, Docker volumes and the caches; if small, caches need an eviction policy | slice 4 sizing |
| 3 | Which KMS backs authentication in production? | separate track | LocalStack stays in the stack for KMS until this is answered; arguably more urgent than this migration | not this migration |

## Risks

- **Partial files become visible.** S3 objects appear atomically; POSIX files do
  not. Upload rows are created with `object_key` first and verified for
  existence and size later (`services/upload.py:585`, `:696`), so a worker can
  observe a half-written file. Every write — first write included — goes to a
  temp name and is renamed into place.
- **Audit export loses Object Lock at cutover**
  (`workers/audit_log_export.py:161-165`), and the wipe guard loses one of its
  three checks (`scripts/check_wipe_guard.py:118-136`). Slice 3 lands first.
- **Janitor age filter** — see the mtime assumption above.
- **Stale cache reads.** `workers/ml/detection.py:154` and
  `workers/ml/embedding.py:129` hardcode `/data/s3_audio_cache`; left in place
  they would keep serving old copies instead of the Lustre originals.

## Slices

Ordered so that every intermediate state runs: change the paths while still on
S3, then cut over once.

### 1. Funnel boto3 through `core/s3.py`

- **Scope** — route every direct boto3 S3 call through the helper module and
  add `scripts/lint_s3_isolation.py`, mirroring `lint_kms_isolation.py`.
  Callers: `services/audio/service.py`, `services/custom_model.py`,
  `api/v1/search/sessions/media.py`, `api/v1/search/batch.py`,
  `workers/upload_tasks.py`, `workers/search_tasks.py`,
  `workers/classifier/utils.py`, `workers/audit_log_export.py`,
  `core/boot_checks.py`, `scripts/check_wipe_guard.py`,
  `scripts/seed_e2e_permissions.py` (`:391`, `:429`).
- **Out of scope** — any behaviour change; no Protocol or store class.
- **Acceptance** — existing suites green; lint fails on a boto3 S3 call outside
  `core/s3.py`.
- **Depends on** — nothing. **UX preview needed** — no.

### 2. Uploads through the backend (still on S3)

- **Scope** — `upload`-scoped media token (`core/auth.py`), streaming write
  endpoint that stores via `core/s3.py`, resumable transfer, atomic GPS
  rewrite, removal of the TOCTOU SHA-256 re-read, the Vite `/s3-proxy`, the
  LocalStack CORS setup and `toRelativeUrl()`.
- **Out of scope** — the storage backend itself.
- **Acceptance** — Playwright spec: upload, interrupt, resume, complete; no
  request leaves the app origin. Security review of the write scope.
- **Depends on** — slice 1. **UX preview needed** — yes (resume and stall
  states in `FileUpload`).

### 3. Audit log immutability without Object Lock

- **Depends on** — open decision 1. **UX preview needed** — no.

### 4. Cutover

One PR, because any subset leaves a broken state.

- **Scope** — POSIX implementation behind `core/s3.py` (temp + rename on every
  write, fresh mtime on copy); `ensure_file_local()` and `get_absolute_path()`
  collapse to `AUDIO_ROOT`; remove the hardcoded `/data/s3_audio_cache` in the
  ML workers; `COMPRESSED_CACHE_DIR` becomes a setting on local disk; boot
  check probes the mount for existence and writability instead of
  `head_bucket`; `/data/audio` mounted read-write; LocalStack reduced to
  `SERVICES=kms`; `CONFIGURATION.md`.
- **Acceptance** — Playwright spec: upload → detection run → playback →
  search by reference audio → model train, with LocalStack S3 disabled.
- **Depends on** — slices 1, 2, 3 and open decision 2. **UX preview needed** — no.

## Review log

| Date | Reviewer | Findings | Resolution |
| --- | --- | --- | --- |
| 2026-09-16 | Codex (gpt-5.5) | Slice order broke browser uploads, audit export and boot check between the old slices 2 and 3-5; `seed_e2e_permissions.py` missing from slice 1; OGG cache hardcoded onto `/data`; `ensure_file_local()` is not the only read path; partial file visibility; janitor mtime; `search_reference/` and `models/` namespaces | All accepted. Slices reordered to "reroute on S3, then cut over once"; the rest folded into Context, Assumptions, Risks and slice scopes |
