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
- Echoroo has not launched: no production data and no compatibility window.
  Existing dev, preview and trial deployments are recreated empty at cutover
  (decision 9).
- `Recording.path` is written as the storage key (`workers/upload_tasks.py:730`)
  and becomes a path under `STORAGE_ROOT`. The data model needs no change.
- Reads resolve local paths in two places, not one:
  `AudioService.ensure_file_local()` (`services/audio/service.py:138`, the S3
  download gate) and `get_absolute_path()` (`:103`), which `read_audio()`
  (`:274`) and `load_clip_bytes()` (`:648`) call. Both collapse to one
  resolver in slice 4.
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
| Local disk | PostgreSQL data directory, Redis dump, Docker volumes and images |

Lustre is built for large sequential I/O; its metadata server is the bottleneck
for files under ~256 KiB. PostgreSQL and Redis never go on Lustre.

The OGG playback cache is currently hardcoded to `/data/audio_compressed`
(`services/audio/service.py:572`). It becomes a setting (slice 4). Its files are
megabytes each and costly to regenerate, so it stays on Lustre, with an
age-based sweep. Spectrograms are rendered per request; there is no disk cache
(the unused `AUDIO_CACHE_DIR` goes). The `/data/s3_audio_cache` copy of every
recording disappears, which frees local disk rather than consuming it.

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
  each call site, so no write can bypass it. Slice 4 removes it with object
  metadata itself: POSIX files carry none.

## Decisions taken

| # | Question | Decision (2026-09-20) |
| --- | --- | --- |
| 1 | How do audit log archives stay immutable without S3 Object Lock? | Tamper evidence from the existing KMS chain hash; immutability provided operationally by a read-only mount and periodic snapshots. No new infrastructure. |
| 5 | Who may upload recordings? (2026-09-22) | **Admin and Owner only.** Overrides spec/006 §Role × Permission (Member ✅ UPLOAD): a Member's upload could never be imported (import needs `MANAGE_DATASET_ADMIN` + session ownership) and the screen starts the import automatically. Member loses `Permission.UPLOAD`; landed in 2d together with the new upload screen. |
| 3 | After a reload, can an unfinished upload be resumed? (2026-09-21) | Yes. The dataset page offers to continue the caller's unfinished session; re-selecting the same files sends only what is missing. |
| 4 | May an upload be imported without the files that failed to transfer? (2026-09-21) | Yes. "Import without the N failed files" is offered next to "Retry". |
| 2 | How much local disk does the VM have? | ~200 GB typical, 500 GB maximum including the OS. See *Data placement* and the embeddings risk below. |
| 8 | Production identity on Lustre (2026-09-24) | The containers run as UID/GID 1000, which can read and write `/data` on the VM. Still verified by `ensure_ready(full=True)` on the mount before first start. |
| 9 | Existing LocalStack objects at cutover (2026-09-24) | **Not carried over** in any deployment. Dev, preview and ninjin are recreated empty (database and LocalStack data discarded); no copy procedure. |

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
  the same code stages on Lustre and the final write is a copy to a temp name
  plus an atomic rename (a move would break retries: import needs the clean
  staged file until its Recording rows commit).
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
  (`/data/upload_staging`), never under the read-only `/data/audio`. Slice 4
  publishes by copy, so staging and storage may sit on different filesystems.
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
- **Status** — done with 2e (2a #273, 2b #274, 2c #275, 2d #276). The
  Playwright spec `apps/web/tests/e2e/upload-resumable.spec.ts` runs in the
  opt-in e2e workflow with a real Celery worker. Rows created before 2e (no
  staged bytes, or an `uploads/` object key) are marked INVALID by the worker
  and must be uploaded again; objects the presigned path left under `uploads/`
  are not cleaned up by code — no production deployment has any, remove dev
  leftovers by hand.
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

Two PRs. **4a** lands `core/storage.py` unused, with its settings and contract
tests — additive, nothing switches. **4b** switches every caller, deletes
`core/s3.py`, and changes deployment configuration together; any subset of 4b
leaves a broken state. 4b is built by parallel implementers on explicitly
assigned files against the 4a API.

**Findings from the pre-slice survey and the design review (2026-09-23)** that
change the original scope:
- `_delete_unlinked_publications` relies on S3 deleting a missing key
  successfully; POSIX delete must report a missing file as deleted.
- Keys become paths: every key needs validation against the root.
- Prefix deletes are string prefixes, not always directory-aligned
  (`search_reference/{p}/{j}` without a slash in `batch.py`, `crud.py`).
- The reference-audio media route forwards the raw `Range` header to S3; POSIX
  has to parse it; an unsatisfiable range becomes 416 instead of today's 500.
- There is no spectrogram disk cache to cap: `AudioService.cache_dir` is created
  and never used. Dropped from scope; the dead setting goes.
- Object metadata disappears, so the FR-028e metadata sanitizer
  (`services/s3_upload_sanitizer.py`) has nothing left to guard. Removed. The
  file-content GPS strip in the upload worker stays.
- A fifth namespace exists: `e2e/` (the permission seeder).
- **Directory-scan import does not exist** (`Dataset.audio_dir` is deprecated,
  the frontend "rescan" calls an unimplemented route) and every recording path
  on dev is `recordings/…` or `e2e/…`. So every key resolves under
  `STORAGE_ROOT` only; the `AUDIO_ROOT` fallback, its setting and the
  `/data/audio` mount go. No shadowing between two roots is possible. A future
  bulk import from Lustre would place files into `STORAGE_ROOT` (a hard link on
  the same filesystem costs nothing).
- The search janitor deletes whole prefixes after classifying only the aged
  keys, so young siblings go too (pre-existing). 4b deletes the enumerated keys.
- `search_tmp/{job}` holds uploaded reference audio, not only the manifest;
  4b makes the manifest point at stored keys and keeps only the manifest there.

**Trust model.** `STORAGE_ROOT` is an application-owned tree: only Echoroo
processes (one numeric UID/GID, see *Deployment*) write under it, and it
contains no symlinks. `path_for` rejects any key whose existing components are
symlinks (`lstat` walk); listing and deletion never follow symlinks. This
guards against mistakes, not against a hostile local user with write access to
the tree.

**Storage API** (`echoroo/core/storage.py`, 4a). Keys keep their S3 form, so
`Recording.path` and every stored key stay valid.

- `class StorageError(Exception)`; `StorageKeyError(StorageError, ValueError)`
  for invalid keys; `StorageUnavailable(StorageError)` when the root is
  missing, unreadable or not the provisioned tree.
- `root() -> Path` — `STORAGE_ROOT`, read from settings on each call.
- `path_for(key) -> Path` — rejects empty keys, a leading `/`, `..` or `.`
  components, empty components (`a//b`), NUL, backslash, a trailing `/`, and
  existing symlink components; the result is `root() / key`.
- `ensure_ready(*, full=False)` — `root()` is a directory owned by the tree
  and contains the provisioning marker `.echoroo-storage` (so a missing mount
  cannot silently redirect writes onto local disk); raises
  `StorageUnavailable`. `full=True` (boot and worker start) additionally
  checks, in `.echoroo-probe/`: create + fsync + replace, hard-link
  publication, collision refusal of a second link, directory fsync, cleanup.
  Any failure raises; there is no fallback to overwriting.
- `exists(key) -> bool` — `False` only for "no such file"; permission and I/O
  errors propagate, and a missing root raises `StorageUnavailable`, so a
  caller never mistakes an outage for absence.
- `size(key) -> int | None` — same error rules.
- `open_read(key) -> BinaryIO` — `FileNotFoundError` when missing; the caller
  closes it. An open handle stays valid across a later replace.
- `read_range(key, range_header: str | None) -> RangeRead` — opens once,
  takes the size with `fstat`. `RangeRead(stream, start, end, total,
  partial)`: `end` inclusive; `stream` is a bounded iterator of chunks that
  closes the file when exhausted or closed. Supported: `bytes=a-b` (b clamped
  to `total-1`), `bytes=a-`, `bytes=-n` (n clamped to `total`). `None` or a
  malformed/multi-range header → the whole file, `partial=False`. `a >= total`,
  or any range on an empty file → `RangeNotSatisfiable(total)`, which the route
  turns into 416 with `Content-Range: bytes */{total}`.
- `write_bytes(key, data, *, exclusive=False) -> int` and
  `write_file(src: Path, key, *, exclusive=False) -> int` — copy (never move;
  the source stays) into `.{name}.tmp-{uuid}` in the destination directory,
  flush, fsync, then publish with `os.replace`, or with `os.link` + unlink of
  the temp when `exclusive` (raises `FileExistsError` if the key exists — the
  write-once primitive). Then fsync the destination directory and every
  directory created for this write, and its parent. The temp is removed in
  `finally`. Fresh mtime always. Returns the byte count. An error after
  publication may leave the object published; callers treat a write error as
  "maybe written" (they already do: upload import deletes on size mismatch,
  audit export reads back).
- `copy(src_key, dst_key) -> int` — `write_file(path_for(src_key), dst_key)`.
- `delete(key) -> bool` — `True` when the file is gone, including when it was
  never there; `False` on an OS error. fsyncs the directory. Never removes
  directories.
- `delete_prefix(prefix) -> int` — S3 string-prefix semantics (a trailing `/`
  and partial final components both work); deletes files only, skips temps,
  returns the count deleted.
- `list_prefix(prefix) -> Iterator[StoredObject]` — `StoredObject(key, size,
  modified)` with `modified` = UTC-aware mtime; files only, temps skipped,
  entries that vanish during the walk are skipped.
- `delete_many(keys) -> BatchDeleteResult(deleted: list[str], errors:
  list[StorageDeletionError(key, code, message)])` — no 1000-key limit.
- `sweep_temporaries(max_age) -> int` — deletes temps older than `max_age`
  (default 24 h), for a daily maintenance task; ordinary operations never
  touch temps.

**Settings** (4a adds, 4b removes): `STORAGE_ROOT` (default `/data/storage`),
`COMPRESSED_CACHE_DIR` (default `/data/audio_compressed`),
`COMPRESSED_CACHE_MAX_AGE_DAYS` (30). 4b removes `S3_*`, `S3_AUDIO_CACHE_DIR`,
`AUDIO_CACHE_DIR`, `AUDIO_ROOT` and the production guard on `S3_SECRET_KEY`.

**4b scope**
- Every caller moves to the API (`workers/upload_tasks.py`,
  `workers/search_tasks.py`, `api/v1/search/batch.py`,
  `api/v1/search/sessions/crud.py`, `api/v1/search/sessions/media.py`,
  `workers/classifier/*`, `services/custom_model.py`,
  `workers/audit_log_export.py`, `services/audio/service.py`, the
  `AudioService` constructions, `workers/ml/*`, `scripts/check_wipe_guard.py`,
  `scripts/seed_e2e_permissions.py`). Readers that downloaded to a temp file
  read the stored path (search sources, classifier models — without the
  `finally: unlink`). The seeder verifies with `open_read` + digest.
- `AudioService`: one resolver, `storage.path_for`; `ensure_file_local()`
  keeps its name and returns that path. OGG cache under the setting, unique
  encoder temps, a hit refreshes mtime, the route streams from an opened
  handle (a sweep between lookup and open → re-encode once).
- Scheduled tasks on the default queue with beat entries: OGG cache sweep
  (daily) and `sweep_temporaries` (daily).
- Boot check and `/health/ready`: component `storage` via `ensure_ready()`
  (`full=True` at boot and worker start); `s3` disappears.
- Audit export publishes with `exclusive=True`; read-back comparison stays.
- `lint_s3_isolation.py` bans the AWS SDK everywhere but `core/kms.py` and any
  import of `core.s3`.
- Tests: `tests/conftest.py` sets unique `STORAGE_ROOT`,
  `UPLOAD_STAGING_DIR` and `COMPRESSED_CACHE_DIR` per test run and xdist
  worker before any application import, with the marker; fakes of the boto
  client go.
- Infra: LocalStack `SERVICES=kms`, bucket creation removed from
  `init-localstack.sh`, compose/CI/e2e/runbook-job env without `S3_*`,
  `STORAGE_ROOT` provisioned with its marker, the LocalStack health predicates
  updated.

**Deployment** (4b, runbook). Storage, staging, the OGG cache and
`search_tmp` are bind mounts of directories on Lustre, the same paths in the
API and every worker, provisioned (owner, mode 0750, marker) before first
start. All Echoroo containers run as one numeric UID/GID that owns them;
published files are 0640, directories 0750; upload staging keeps its
0700/0600. The containers run as UID/GID 1000 (decision 8). Existing
deployments are not migrated (decision 9): stop everything, discard the
database and the LocalStack data, provision the storage tree, start the new
version, re-run the initial setup. Backup/restore and release-readiness runbooks change with it.

- **Out of scope** — deleting a recording's file when the recording, dataset or
  project is deleted (never done on S3 either); renaming `s3_key` / `origin:
  's3'` in API schemas and the frontend (names only).
- **Acceptance** — CI: the e2e workflow and the runbook job run with LocalStack
  `SERVICES=kms`; the upload spec also plays back an imported recording;
  `/health/ready` reports `storage`; integration tests without model weights
  cover ML audio resolution (`workers/ml/utils.py`), search sources with
  inference stubbed, classifier train/save/load on synthetic vectors, both
  export paths, range responses, concurrent exclusive publication, readers
  across a replace, upload retry and reaper. By hand on dev: real detection,
  embedding, search and training. On the production VM: `ensure_ready(full=True)`
  on the Lustre mount.
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
| 2026-09-22 | Astra, slice 2b third pass | After a reset released the locks, neither path repeated the reconciliation (a concurrent finish could be counted missing and skipped; a second reset could proceed unlocked); inline Pydantic schema left an unresolved `$defs` ref | Accepted: `_lock_and_reconcile` loop (session lock → file lock → reconcile, repeated until no reset) used by chunk append and completion; 409 schema inlined without refs |
| 2026-09-22 | Astra, slice 2b fourth pass | Completion kept decisions for earlier files after a later file's reset released the locks | Accepted: `_lock_and_reconcile` reports whether locks were released; completion restarts the whole pass on fresh rows |
| 2026-09-23 | Astra, slice 2c code review | Redelivered tasks could overwrite a terminal state with FAILED; a crash between publish and commit orphaned a `recordings/` object; Recording rows and their UploadFile links committed separately; IMPORTED committed before the dataset's COMPLETED; the reaper deleted bytes of a session that had come back to life; no heartbeat inside a long file; rename not fsynced; tests lacked duplicate-delivery and race cases | Accepted: failure marking only from an owned processing state with a CAS; staged files publish to a deterministic key (recording id = upload file id) so a re-run overwrites instead of orphaning; one commit for rows + links + progress and for IMPORTED + dataset; reaper re-reads under lock, re-checks, claims FAILED, commits, then deletes; heartbeats before hash and upload; directory fsync; duplicate-delivery and reaper-race tests. Not adopted: a lease renewed from a second DB session — the per-step heartbeats keep any single step well under the 15-minute stale window for 1 GiB files |
| 2026-09-23 | Astra, slice 2c passes 2–4 | Duplicate delivery after VALIDATED still failed the session; failure helpers accepted any owned state; `_mark_import_failed` failed the dataset without the CAS; reaper iterated expired ORM rows and crashed on a `noload`ed relationship; heartbeats did not cover hash / sanitise / write / upload; deletion failures lost their retry; a force-fail during an in-flight PUT orphaned the object | Accepted: failure marking is a CAS on the exact owned state; `_with_heartbeat` covers every long step with a second DB session; reaper works on captured scalars; `_delete_unlinked_publications` keeps the staging directory until every object is gone and the sweep covers IMPORTED sessions; a batch rejected by the session lock deletes its own objects. Residual, documented: a worker that dies mid-PUT can leave an object that lands after cleanup — an operational orphan scan of `recordings/` against the `recordings` table is a follow-up |
| 2026-09-23 | Fable, slice 2d browser verification (dev stack, Playwright) | Fresh 3-file upload (29 MB, 6 chunks) → validated → imported → S3 objects and Recording rows correct, staging removed. Reload during validation stranded a finished upload (`/active` only returned `issued`; the reaper would have failed it after 15 min). Resume after reload never started (`sessionId` unset). A silently dead connection (backend paused) hung a chunk forever. | All fixed: `/active` returns any non-terminal session and the page resumes polling; `sessionId` set on resume; 30 s no-progress watchdog. Re-verified: resume after reload sends only the remaining 32 of 35 chunks; a 45 s server stall is recovered by watchdog → retry → 409 resync → completion with no duplicate bytes |
| 2026-09-23 | Astra, slice 2d code review | Backend: supersede deleted staging before the replacement committed and decided on an unlocked snapshot; restart wrote replacement bytes before the reset was durable. Browser: retry used optimistic progress as the offset and dropped pending restarts; completion's `issued` response ignored; resume auto-skipped files the user was told they could still add; no verifying state (double selection → two schedulers); 5xx fatal; late 401 → second refresh; discard from the banner did not cancel; 'import without' offered with nothing uploaded; stall cap measured total time; scheduler not aborted on destroy; `file(s)` plurals | All accepted except the plural NIT (English-only wording; ja unaffected) — see commits d94be374 and the 2d-fix commit |
| 2026-09-23 | Astra, slice 2d re-review | Choosing missing files replaced pending restarts; a queued old request could overtake the restart reset and an offset conflict was taken as its acknowledgement; creation locked dataset→session while import finalised session→dataset (deadlock); `issued` recovery trusted stale local offsets; completed server files counted as unmatched; fresh runs unguarded on destroy; partial-import enablement and exclusion count wrong | All accepted: restart re-checks after re-lock (3 tries) and is acknowledged only by `ok`; dataset→session everywhere; offsets rebuilt from `/active`; `alreadyComplete` in the resume plan; generation guard; counts from current state |
| 2026-09-23 | Fable, slice 2e e2e run (dev stack) | The upload spec passed 5/5 twice against the real backend, Celery worker and LocalStack; recordings land at the reserved `recordings/{p}/{d}/{file_id}` key. A third pass hit 429 on session creation: the create/complete limiters key on the direct peer, which behind the BFF is the frontend container, so every user of a dataset shares 10 creations per hour | CI raises the create limit for the e2e job (Playwright retries the serial group). Per-user limiter keys for create/complete split off as a separate task (pre-existing since before slice 2) |
| 2026-09-23 | Astra, slice 2e code review | With the presigned branches gone, a pre-2e VALID file with no staged bytes imported without any existence/size/hash check, and a staged 2d-era file published under its `uploads/` key; legacy `uploads/` objects are no longer cleaned; e2e: retries share one dataset, resume assertions pass on an empty set, origin checked by string prefix; `mismatched_files` always 0; ruff F841/ARG001 | Accepted: validation and import refuse files without staged bytes or outside the reserved key (INVALID, no Recording, no write), regression tests; each test cancels the owner's unfinished session first; resume must continue the original session at 16 MiB and every session is checked for `imported` + `recording_id`; exact origin match; `mismatched_files` removed; lint fixed. Not adopted: cleanup code for legacy `uploads/` objects — pre-launch, none in production |
| 2026-09-23 | Astra, slice 4 design review | Named volume ≠ Lustre and no guard against an absent mount; shared identity and file modes unspecified; existence-based two-root lookup allows shadowing; "final write is a rename" breaks import retries; durability of new ancestor directories and of deletes; readiness probe did not test link/replace; parent-directory pruning races writers; range contract loose; API contract too vague for parallel implementers; live `s3 sync` is not a cutover; test isolation across xdist workers; janitor deletes young siblings; symlink trust model; orphaned temps; `search_tmp` holds audio; cache sweep races; CI could cover more without models; file ownership across the parallel split; earlier sections contradicted slice 4 | All accepted. Split into 4a (API unused) and 4b (switch); single root (directory import does not exist); copy-then-publish; fsync of every created directory and after unlink; `ensure_ready(full=True)` with link/collision/replace probe and a provisioning marker; no directory pruning; exact range contract; full API contract; maintenance-window runbook; per-run/per-worker roots in conftest; janitor deletes enumerated keys; application-owned tree without symlinks; temp sweep; manifest points at stored keys; unique encoder temps and handle-based streaming; CI integration tests without weights; earlier sections reconciled. Production identity and data carry-over settled as decisions 8 and 9 (UID/GID 1000; nothing carried over) |
