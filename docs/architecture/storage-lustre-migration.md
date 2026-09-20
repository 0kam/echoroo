# Storage migration: LocalStack S3 to Lustre POSIX

Status: decided (2026-09-20)

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

The VM's local disk is small: about 200 GB in normal use, 500 GB at most,
operating system included. Lustre is 20 TiB. Anything large goes to Lustre
unless it needs random I/O.

| Location | Contents |
| --- | --- |
| Lustre `/data` | Recording originals, model artifacts, search reference audio, OGG playback cache |
| Local disk | PostgreSQL data directory, Redis dump, Docker volumes and images, spectrogram cache (size-capped) |

Lustre is built for large sequential I/O; its metadata server is the bottleneck
for files under ~256 KiB. PostgreSQL and Redis never go on Lustre.

The OGG playback cache is currently hardcoded to `/data/audio_compressed`
(`services/audio/service.py:576`). It becomes a setting (slice 4). Its files are
megabytes each and costly to regenerate, so it stays on Lustre, with an
age-based sweep. The spectrogram cache holds many small PNGs and stays on local
disk under a size cap. The `/data/s3_audio_cache` copy of every recording
disappears, which frees local disk rather than consuming it.

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
- **Callers never hold a storage client (slice 1).** Helpers in `core/s3.py`
  build one per call (3 ms measured); `core/s3.ensure_configured()` sits where
  `get_s3_client()` used to be called, so a malformed configuration still
  aborts a task instead of being swallowed by a per-file `except`. Reversible:
  the helpers keep an optional `client=` parameter. In slice 4
  `ensure_configured()` becomes the mount probe.
- **The FR-028e metadata sanitizer runs inside `core/s3.put_object`**, not at
  each call site, so no write can bypass it. Reversible.

## Decisions taken

| # | Question | Decision (2026-09-20) |
| --- | --- | --- |
| 1 | How do audit log archives stay immutable without S3 Object Lock? | Tamper evidence from the existing KMS chain hash; immutability provided operationally by a read-only mount and periodic snapshots. No new infrastructure. |
| 2 | How much local disk does the VM have? | ~200 GB typical, 500 GB maximum including the OS. See *Data placement* and the embeddings risk below. |

## Open decisions

| # | Question | Options (recommended first) | Consequence | Blocks |
| --- | --- | --- | --- | --- |
| 3 | Which KMS backs authentication in production? | separate track | LocalStack stays in the stack for KMS until this is answered; arguably more urgent than this migration | not this migration |
| 4 | How many hours of recordings is this deployment expected to hold? | — (fact needed) | Above roughly 10,000 hours the embeddings outgrow local disk; see Risks | nothing here; sets the deadline for the embeddings follow-up |

## Risks

- **PostgreSQL fills before Lustre does.** Embeddings live in PostgreSQL as
  `Vector(1536)` (`models/embedding.py:42`): about 4.5 MB of row data per
  recorded hour at one vector per 5 s, roughly 10 MB with the index. With
  ~100 GB of local disk left for PostgreSQL that is on the order of 10,000
  hours, while 20 TiB of Lustre holds about 60,000 hours of WAV. Not in scope
  here. First lever when it approaches: `halfvec` (halves it). Second: move
  embeddings out of PostgreSQL. Watch `pg_database_size` against local disk.

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
- **Status** — done. The lint bans three things outside `core/s3.py`:
  `client("s3")` / `resource("s3")` on any receiver, the raw-client accessors
  `get_s3_client` / `get_public_s3_client`, and any AWS SDK import
  (`core/kms.py` exempt). No allowlist file: there are no exemptions.
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

- **Scope** — audit export writes through `core/s3.py` without Object Lock
  parameters; archives land under a directory that operations mounts read-only
  and snapshots; the wipe guard's genesis-marker check reads the same path;
  runbook entry for the mount and snapshot schedule.
- **Out of scope** — the chain hash itself, which already exists.
- **Acceptance** — export then verify the chain end to end; wipe guard still
  refuses when the marker is present.
- **Depends on** — slice 1. **UX preview needed** — no.

### 4. Cutover

One PR, because any subset leaves a broken state.

- **Scope** — POSIX implementation behind `core/s3.py` (temp + rename on every
  write, fresh mtime on copy); `ensure_file_local()` and `get_absolute_path()`
  collapse to `AUDIO_ROOT`; remove the hardcoded `/data/s3_audio_cache` in the
  ML workers; `COMPRESSED_CACHE_DIR` becomes a setting (Lustre, age-based sweep) and the spectrogram cache gets a size cap; boot
  check probes the mount for existence and writability instead of
  `head_bucket`; `/data/audio` mounted read-write; LocalStack reduced to
  `SERVICES=kms`; `CONFIGURATION.md`.
- **Acceptance** — Playwright spec: upload → detection run → playback →
  search by reference audio → model train, with LocalStack S3 disabled.
- **Depends on** — slices 1, 2, 3. **UX preview needed** — no.

## Review log

| Date | Reviewer | Findings | Resolution |
| --- | --- | --- | --- |
| 2026-09-16 | Codex (gpt-5.5) | Slice order broke browser uploads, audit export and boot check between the old slices 2 and 3-5; `seed_e2e_permissions.py` missing from slice 1; OGG cache hardcoded onto `/data`; `ensure_file_local()` is not the only read path; partial file visibility; janitor mtime; `search_reference/` and `models/` namespaces | All accepted. Slices reordered to "reroute on S3, then cut over once"; the rest folded into Context, Assumptions, Risks and slice scopes |
| 2026-09-20 | Maintainer | Decisions 1 and 2; local disk is ~200 GB | Audit slice unblocked; OGG cache moved to Lustre, spectrogram cache capped; embeddings-vs-local-disk risk recorded with open decision 4 |
| 2026-09-20 | Astra (gpt-6-astra), slice 1 code review | Building the client per helper call moved construction errors inside per-item `except` blocks (valid uploads marked INVALID, cleanup marking sessions FAILED, recordings 404, search sources skipped); lint missed `from boto3 import client`; a missing scan root passed as clean | All accepted: `ensure_configured()` at every former `get_s3_client()` site with regression tests; SDK-import rule; missing root exits 2. Not accepted: linting raw operations on passed-in clients — no module can obtain one |
