# Storage migration: LocalStack S3 to Lustre POSIX

Status: planned (2026-09-16)

## Decision

Drop the S3 object-storage layer entirely and read/write recordings directly on
the Lustre parallel filesystem mounted at `/data`.

Rationale:

- The only S3 implementation in use is LocalStack, pinned to
  `localstack/localstack:community-archive` (the final token-free build, no
  further updates). There is no production compose file. Running this in
  production is not an option, so *some* migration is mandatory.
- The usual drop-in replacement is gone: MinIO removed the community admin UI in
  2025 and archived its repository in April 2026. Adopting Garage, SeaweedFS or
  Ceph RGW would mean operating a distributed object store for a benefit Lustre
  already provides.
- Lustre is mounted POSIX at `/data` and is reachable from several VMs in the
  project. Shared multi-node access — the main reason to run an object store —
  is satisfied by the filesystem.
- Echoroo has not launched. There is no data to migrate and no compatibility
  window, so we replace the implementation in place rather than running two
  backends behind an abstraction.

## What already points this way

- `Recording.path` is written as the S3 key (`workers/upload_tasks.py`) and is
  simultaneously interpreted as a path relative to `AUDIO_ROOT`. The data model
  needs no change: `recordings/{project_id}/{dataset_id}/{recording_id}.wav`
  becomes a real directory tree.
- Every API-side read goes through the single gate
  `AudioService.ensure_file_local()` (`services/audio/service.py`), which
  already returns early when the file exists under `AUDIO_ROOT`. Once Lustre is
  `AUDIO_ROOT`, the S3 download branch becomes dead code.
- The API and the Celery workers already share a POSIX volume (`backend-data:/data`).
- No multipart upload is used anywhere, so no multipart state machine has to be
  reimplemented.
- Spectrograms and export artifacts never touch S3 — they are generated on
  demand and streamed in the response.

Two operations get faster: `move_object` (copy + delete) becomes an atomic
`os.rename` on the same filesystem, and the TOCTOU SHA-256 re-read of every
uploaded file (1 GB read twice) disappears once uploads no longer land through a
presigned URL.

## Data placement

| Location | Contents |
| --- | --- |
| Lustre `/data` | Recording originals, model artifacts, search reference audio |
| Local NVMe | PostgreSQL data directory, Redis dump, Docker volumes, `AUDIO_CACHE_DIR` (spectrogram PNG / OGG playback cache) |

Lustre is optimised for large sequential I/O. Its metadata server becomes the
bottleneck for files under ~256 KiB, so the derived-image cache stays on local
disk. PostgreSQL and Redis are never placed on Lustre.

The application does not use `flock`, and PostgreSQL does not live on Lustre, so
no cluster-wide locking guarantees are required from the mount.

## The three hard parts

### 1. Browser uploads via presigned PUT

POSIX has no equivalent of "a URL the browser may write to". Presigned URLs are
generated in exactly one place (`services/upload.py`), consumed by
`apps/web/src/lib/api/uploads.ts`.

Replacement: upload through the backend, authorised by an `upload`-scoped media
token. The HMAC token machinery already exists (`issue_media_token` /
`verify_media_token` in `core/auth.py`, introduced in W2-4) and is currently
read-only; adding a write scope needs its own security review.

This also removes the Vite `/s3-proxy` reverse proxy, the LocalStack CORS
configuration and the `toRelativeUrl()` workaround, and it is the natural point
to add resumable uploads (today a dropped 1 GB upload must be redone inside the
15-minute presigned window).

### 2. S3 Object Lock (audit log WORM)

`workers/audit_log_export.py` writes weekly NDJSON with
`ObjectLockMode=GOVERNANCE`, and `scripts/check_wipe_guard.py` treats the
presence of an Object Lock genesis marker as one of three database-wipe guards.
Lustre offers no equivalent.

This is a compliance question rather than a technical one. Options:

- keep the audit archive on an external append-only store (hybrid), or
- rely on the existing KMS chain hash for tamper evidence and provide
  immutability operationally (read-only mount plus periodic snapshots).

Pending a decision.

### 3. In-place overwrite atomicity

GPS stripping overwrites the uploaded object in place (`put_object` in
`workers/upload_tasks.py`). S3 replaces atomically; a POSIX `open(w)` exposes
intermediate state. Must become write-to-temp plus `os.rename`.

## KMS is a separate problem

S3 server-side encryption is not used anywhere — recordings, model artifacts and
audit archives are stored in plaintext. LocalStack KMS instead backs four
application concerns: TOTP secret envelope encryption, PII HMAC, the audit log
chain hash and invitation token signing.

Removing S3 therefore does not remove LocalStack. The authentication
infrastructure would still depend on an unmaintained build. Choosing a real KMS
backend is tracked separately and is arguably more urgent than this migration.

## PR slices

1. **Funnel boto3 through `core/s3.py`.** Eight modules call boto3 directly
   (`services/audio/service.py`, `services/custom_model.py`,
   `api/v1/search/sessions/media.py`, `api/v1/search/batch.py`,
   `workers/upload_tasks.py`, `workers/search_tasks.py`,
   `workers/classifier/utils.py`, `workers/audit_log_export.py`, plus
   `core/boot_checks.py` and `scripts/check_wipe_guard.py`). Route them through
   the helper module and add `scripts/lint_s3_isolation.py`, mirroring the
   existing `lint_kms_isolation.py`. Behaviour unchanged.
2. **Replace `core/s3.py` with a POSIX implementation** and switch reads to
   Lustre: collapse `ensure_file_local()`, drop the hardcoded
   `/data/s3_audio_cache` in `workers/ml/detection.py` and
   `workers/ml/embedding.py`, mount `/data/audio` read-write.
3. **Move uploads through the backend**: `upload` scope on the media token,
   streaming write endpoint, resumable transfer, atomic GPS rewrite, and removal
   of the now-unnecessary TOCTOU re-read.
4. **Audit log WORM replacement** (blocked on the compliance decision above).
5. **Retire S3 from the stack**: LocalStack down to `SERVICES=kms`, boot check
   probes the mount instead of the bucket, compose and `CONFIGURATION.md`
   updated.

Estimated blast radius: roughly 20 production files and 20 test files.
