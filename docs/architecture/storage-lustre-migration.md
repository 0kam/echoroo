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
| 5 | Who may upload recordings? (2026-09-22) | **Admin and Owner only.** Overrides spec/006 §Role × Permission (Member ✅ UPLOAD): a Member's upload could never be imported (import needs `MANAGE_DATASET_ADMIN` + session ownership) and the screen starts the import automatically. Member loses `Permission.UPLOAD`; landed in 2d together with the new upload screen. |
| 3 | After a reload, can an unfinished upload be resumed? (2026-09-21) | Yes. The dataset page offers to continue the caller's unfinished session; re-selecting the same files sends only what is missing. |
| 4 | May an upload be imported without the files that failed to transfer? (2026-09-21) | Yes. "Import without the N failed files" is offered next to "Retry". |
| 2 | How much local disk does the VM have? | ~200 GB typical, 500 GB maximum including the OS. See *Data placement* and the embeddings risk below. |

## Open decisions

| # | Question | Options (recommended first) | Consequence | Blocks |
| --- | --- | --- | --- | --- |
| 3 | Which KMS backs authentication in production? | separate track | LocalStack stays in the stack for KMS until this is answered; arguably more urgent than this migration | not this migration |
| 4 | How many hours of recordings is this deployment expected to hold? | — (fact needed) | Above roughly 10,000 hours the embeddings outgrow local disk; see Risks | nothing here; sets the deadline for the embeddings follow-up |
| 7 | What does the Lustre service offer for the audit archive: filesystem snapshots (who can take and delete them, how often)? Can a second VM or auditor account mount read-only? | snapshots by the provider + read-only mount for auditors; else weekly `rsync --ignore-existing` to a location owned by another account | Without either, archive immutability rests on detection only (MAC chain + gaps) | the *ops* section of `docs/runbook/audit_log_archive.md`; not slice 4 |

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

**Why it is more than a transport swap.** Today the browser PUTs each file to a
presigned URL that signs only bucket and key, so for 15 minutes anyone holding
the URL can write any bytes of any size. Everything downstream exists to
compensate: the worker downloads, strips GPS and re-uploads (a non-atomic
rewrite of a client-writable object) and re-hashes the whole object again at
import. In the browser, SHA-256 loads each file fully into memory and hashes
all files before the first byte is sent; one failed PUT fails the whole batch;
nothing retries or resumes; there is no upload e2e test.

**Design.**

- *Transport* — the browser sends each file in 8 MiB chunks:
  `PUT /web-api/v1/projects/{p}/datasets/{d}/upload-sessions/{s}/files/{f}/chunks?offset=N`
  with the raw bytes as the body and an optional `X-Chunk-SHA256`. The server
  accepts a chunk only at `offset == bytes already staged` and answers 409 with
  the current offset otherwise, which is the whole resume protocol. Three files
  in flight; each chunk retried up to 5 times with backoff; offline pauses and
  resumes; a failure is confined to its file.
- *Auth* — the ordinary BFF session: Bearer + CSRF + `gate_action(UPLOAD_CREATE)`
  + "session created by the caller". **No `upload`-scoped media token**
  (deviation from the earlier scope): media tokens exist because `<audio>` and
  `<img>` cannot send headers, which XHR can; chunk requests are short, so the
  15-minute access token and its refresh are enough; and a write-capable JWT
  scope signed with the same key as read tokens would widen the blast radius
  for nothing.
- *Staging* — chunks are appended to
  `UPLOAD_STAGING_DIR/{session}/{file}.part` on the POSIX volume the API and the
  workers already share (`/data`). The object store is written exactly once per
  file, by the import worker, from the staged file after validation and GPS
  stripping — straight to the `recordings/` key. The `uploads/` prefix, the GPS
  read-modify-write and the import-time SHA-256 re-read disappear. After slice 4
  the same code stages on Lustre and the final write is a rename.
- *Integrity* — the server hashes what it receives (per chunk against
  `X-Chunk-SHA256` when the browser can compute it, whole file during
  validation). The browser no longer hashes whole files up front.
- *Limits* — the chunk endpoint caps the body at the chunk size (413 beyond),
  rejects chunks for files that are complete or sessions that are not `issued`,
  and never lets a file exceed its declared size.
- *Resume after reload* — `GET …/upload-sessions/active` returns the caller's
  unfinished session with per-file `received_bytes`; files are matched by name
  and size.
- *Partial import* — `complete` takes `skip_missing`; missing files are marked
  skipped and the rest proceed.
- *Removed* — presigned URLs (`generate_presigned_upload_url`,
  `get_public_s3_client`, `S3_PUBLIC_ENDPOINT_URL`, `S3_PRESIGNED_URL_EXPIRY`),
  the Vite `/s3-proxy` and its `hooks.server.ts` exception, the LocalStack
  bucket CORS and gateway CORS settings, `toRelativeUrl()`.

**Refinements from the design review (Astra, 2026-09-21).**

- *Data model* (migration after `0036`): `upload_files.received_bytes`;
  `declared_size` kept apart from the post-sanitisation `file_size`; status
  `skipped`; `object_key` becomes the reserved final `recordings/` key (no
  filesystem paths in the database); per-chunk server digests, so a resumed
  file can be checked against the prefix already staged; at most one active
  session per dataset, enforced by a constraint.
- *Resume needs more than name + size.* The same name and size do not prove the
  same content; appending to a staged prefix from a different file would splice
  two recordings. On resume the browser re-hashes the chunks the server already
  holds and the server compares digests before accepting new bytes.
- *Sessions are no longer silently superseded.* Today `create_session()` fails
  any `issued`/`uploaded` session of the dataset, whoever created it; with
  resumable uploads that would destroy someone's staged data. Creation returns
  the conflict instead; the owner resumes or cancels explicitly.
- *Expiry becomes inactivity retention*: 24 hours, extended by every accepted
  chunk and by an explicit resume, not by polling. The 1-hour `expires_at` and
  the 15-minute presign clock go away.
- *Auth in the browser*: an XHR wrapper that reuses the client's
  `getAccessToken()` / `refreshToken()`, re-reads the CSRF cookie per attempt,
  ignores a late 401 when the token has already been refreshed, and stops on
  419. The session cookie is required in addition to Bearer + CSRF.
- *Server admission*: three files in flight is a browser courtesy, not a limit.
  The chunk route caps concurrent staging per user and reserves quota under a
  lock at session creation.
- *Workers*: validate the staged file locally, sanitise into a new local file,
  always hash the final bytes, publish once to the reserved key, link the
  recording in the same transaction; duplicate delivery must be harmless;
  processing heartbeats so long batches are not reaped; the janitor removes
  staging directories of terminal and orphaned sessions, including those whose
  rows were cascaded away.
- *Staging location*: its own directory on the shared `backend-data` volume
  (`/data/upload_staging`), never under the read-only `/data/audio`. The
  "final write becomes a rename" claim holds only if staging and recordings end
  up on the same filesystem — a slice 4 placement constraint.
- *Known amplification, accepted for now*: the GPS sanitiser still reads a whole
  file into memory; staging uses local disk until slice 4.

**Sub-slices** (one PR each; the transport switches only in 2d, so every
intermediate state runs):

| # | Content | Can ship alone because |
| --- | --- | --- |
| 2a | Migration, models, enums, schemas, settings, staging utility | additive; nothing uses it yet |
| 2b | Chunk / active / cancel routes, `complete(skip_missing)`, admission limits, tests against real middleware | new routes next to the old flow |
| 2c | Workers and janitor accept staged files as well as `uploads/` objects; heartbeats; idempotent publish; every worker status transition conditional on the expected status (a validator finishing after its session was force-failed and replaced must stop, not resurrect it into the unique index) | old sessions keep working |
| 2d | Browser scheduler, resume UI, i18n for the four upload components; `Permission.UPLOAD` removed from Member (decision 5) with matrix tests, `can()` matrix and the upload entry point hidden for Members | flips the transport; old routes still exist |
| 2e | Remove presign, `/s3-proxy`, CORS, `toRelativeUrl()`, the `uploads/` code paths; Playwright upload spec with a real worker in CI | nothing references them after 2d |

- **Out of scope** — the storage backend itself.
- **Acceptance** — Playwright spec that stays in CI: upload, interrupt, resume,
  complete; partial import; no request leaves the app origin. Security review
  of the write endpoint.
- **Depends on** — slice 1. **UX preview needed** — yes; shown 2026-09-21
  (sending / connection lost / some failed / unfinished upload after reload),
  decisions 3 and 4 above.

### 3. Audit log immutability without Object Lock

- **Scope** — audit export writes through `core/s3.py` without Object Lock
  parameters; archives land under a directory that operations mounts read-only
  and snapshots; the wipe guard's genesis-marker check reads the same path;
  runbook entry for the mount and snapshot schedule.
- **Out of scope** — the chain hash itself, which already exists.
- **Acceptance** — export then verify the chain end to end; wipe guard exit
  codes unchanged.
- **Status** — done. Found while slicing: the export task was never registered
  with Celery (no `include`, no beat entry), so it had never run; it is now
  scheduled Mondays 03:00 UTC. Without Object Lock the code itself has to be
  write-once, so each archive is one *closed* ISO week (deterministic
  contents), an existing key is skipped rather than overwritten, the archive
  is read back and re-verified after writing, and an 8-week look-back catches
  up missed runs. The wipe guard reads the genesis marker through `core/s3`
  from the same bucket. Runbook: `docs/runbook/audit_log_archive.md`.
- **Follow-up, not in this slice** — a signed manifest per archive (row count
  and digest recorded as a MAC-chained `platform_audit_log` event) would make
  tail truncation detectable from the archive alone after the 8-week window.
  Today that needs the live table, the next archive or a snapshot.
- **Not changed, flagged** — `check_wipe_guard.py` contradicts itself: the
  docstring and `all_clear_for_wipe` expect the genesis marker to be *absent*
  before a wipe, `main()` refuses when it is absent (exit 12). Behaviour left
  as is; which one is intended is a release-ritual question for the
  maintainer.
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
| 2026-09-20 | Astra, slice 1 re-review | `search/batch.py` lost its fail-fast when a rerun carries no new uploads (empty search job instead of HTTP 500); the lint missed an SDK module re-exported through `core/kms.py` | Accepted: `ensure_configured()` before the upload loop, pinned by the wiring test; re-export rule added. Not accepted: alias/data-flow tracking inside `core/kms.py` — the lint guards against accidents, same stated limit as `lint_kms_isolation.py` |
| 2026-09-21 | Astra, slice 3 code review | Task routed to a queue no worker consumes; HEAD-then-PUT is not write-once under concurrency; `verify_archive` authenticated rows but not order or completeness; a row committed into an already archived week was silently skipped; one read-back failure blocked the clean weeks; naive `now_iso`; tests faked the SQL window and signed fixtures with the verifier's own canonicaliser; bootstrap `genesis` rows (zero hashes by design) would block the first production week; IAM `ListBucket` | All accepted: default queue; PostgreSQL advisory lock; chain-link check plus empty/malformed detection; every archive in the window is byte-compared with the live table on every run; failures aggregate per week; naive = UTC; fixtures signed with `audit_service._build_canonical_row`, real query asserted; bootstrap actions accepted without a MAC. Deferred: signed manifest (above). Not accepted: a persisted write cutoff in the audit writer — detection is enough before launch |
| 2026-09-21 | Astra, slice 3 re-review | The bootstrap exception allowed a whole week to be replaced by a forged zero-hash row (links restarted each week); a storage error on one key still aborted the run; `verify_archive` ignored week membership and leaked raw exceptions; runbook omitted prefix truncation and silent recreation | All accepted: each week's first row must link to the row before it (confines bootstrap rows to the chain start), `verify_archive(expected_prev_hash=…)`, per-week isolation of any exception, week-membership check, normalised errors, runbook matrix corrected |
| 2026-09-21 | Astra, slice 3 third pass | A forged zero-hash row outside the catch-up window could make a later forged bootstrap week link correctly; archive rows were not shape-checked; a non-week key skipped the week check; runbook wording | Accepted: a bootstrap week is refused when any signed row precedes it (whole table, not just the window); required-field and type checks; non-week keys rejected; runbook corrected. Not accepted, recorded: (a) rows sharing one microsecond timestamp are ordered by random UUID, so a legitimate week could fail verification — 0 of 1,012 real rows tie, the failure is a visible false alarm, and the fix belongs in the audit writer (a monotonic sequence column), not here; (b) isolating database read failures per week with savepoints — if the database fails, aborting the run is the right outcome |
| 2026-09-21 | Astra, slice 2 design review | The shared volume and middleware claims hold; missing: data model and migration, wrong-file resume splicing recordings, silent superseding of another user's session, expiry vs. resume, token refresh races in the browser, no server-side admission limit, duplicate task delivery, staging cleanup on cascade deletes, rename only works on one filesystem, Member-upload vs Admin-import permission gap, no production same-origin proxy | Folded into the slice 2 section as refinements and sub-slices 2a–2e; permission gap raised as open decision 6 |
| 2026-09-21 | Astra, slice 2a code review | The new unique index turned concurrent session creation into an IntegrityError (500); fsync of the part file does not persist new directory entries; the test-DB heal skipped the CHECK constraints, the dedup and, after an interrupted run, the enum label; an unconditional worker transition can now collide with a replacement session | Accepted: creation serialised with a dataset row lock (also serialises the quota check); directory fsync; heal probes and installs every piece; reconciliation contract documented in `core/upload_staging.py`. The worker transition moves to 2c |
| 2026-09-22 | Astra, slice 2b code review | Row lock returned a stale identity-map copy (loser of a same-offset race truncated committed bytes); `request.body()` buffered before the size check; the lost-bytes reset was rolled back with the 409; session status read outside any lock; cancel ignored the CAS and deleted files before commit; completion trusted counters without the file; cancelled requests left the thread writing; bytes acknowledged before commit; rate-limit bucket keyed on X-Forwarded-For + path; 409 schema did not match the wire | All accepted: `populate_existing` + a session row lock shared by chunk/complete/cancel; streamed body with cap; reset committed then locks re-taken; cancel honours CAS and removes files after commit; completion checks the staged size; `_run_blocking` waits for the thread on cancellation; explicit commit before the 200; per-user limiter identifier; envelope model; concurrency regression test |
| 2026-09-22 | Astra, slice 2b re-review | The thread wait was itself cancellable; completion truncated an uncommitted tail to zero and its reset rolled back with the 409; no re-reconcile after re-taking the locks; OpenAPI lacked the binary body and the string-detail 409 | All accepted: uncancellable wait loop; completion reuses `_reconcile_staged_file` (commits the reset, re-locks); re-reconcile after re-lock; `openapi_extra` body + `oneOf` 409 |

