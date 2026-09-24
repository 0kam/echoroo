# Key management without LocalStack: a local keyring

Status: decided (2026-09-24)

## Decision

Replace the LocalStack KMS calls behind `core/kms.py` with a local keyring: a
file of named 256-bit keys, provisioned once per deployment, bind-mounted
read-only into the containers that need it, and backed up separately from the
database. Wrapping (AES-256-GCM) and HMAC-SHA256 run in the application. Then
remove LocalStack from every stack.

**Accepted trade-off against OpenBao/Vault Transit.** An isolated Transit
service keeps master keys out of the application process, enforces per-caller
policy and audits each operation, so an application-only compromise could use
the keys but not copy them out. On one VM run by one maintainer, that service
must itself be unsealed, backed up and upgraded, and host root defeats it.
We accept that the application process holds key material in memory, in
exchange for no additional service. The keyring sits behind the same function
names, so a Transit backend can replace it later without touching callers.
This supersedes two properties stated in `core/kms.py`: key material is now
in-process (`:33`), and rewrap exposes the plaintext DEK to the process
(`:274`).

## Context

Checked on main `1231e736` (2026-09-24):

- **The current keys are public.** `scripts/init-localstack.sh:104-106`
  derives every key as `sha256("echoroo-dev-kms-fixed-material-v1:<alias>")`
  with fixed key ids (`:79-87`). The LocalStack service has no `env_file`
  (`compose.dev.yaml:67-95`), so the documented seed override
  (`.env.example:212-217`) never reaches it, and no `AWS_KMS_CMK_*` variable is
  passed to the app containers. Every stack started from this compose file,
  including the planned production VM, would encrypt TOTP secrets and MAC the
  audit chain with material computable from the repository.
- LocalStack is pinned to the last token-free build and will not be updated;
  after the storage cutover it exists only for KMS.
- What the application needs (`core/kms.py`, the only client): wrap/unwrap of
  a locally generated 32-byte DEK under a named symmetric key (`wrap_dek` :209,
  `unwrap_dek` :237, `rewrap_dek` :266 for the rotation script), and
  deterministic HMAC-SHA256 as lowercase hex under two keys: PII
  (`compute_pii_hash*` :313-432, `verify_pii_hash` :435; UTF-8 input, :371) and
  the audit chain (`compute_audit_chain_hash` :610; ASCII previous hash plus
  canonical row, :631). No encryption context, GenerateDataKey, policies,
  grants or asymmetric keys.
- Dead code: `alias/echoroo-invitation-hmac` with `sign/verify_invitation_hmac`
  (tests only; invitation tokens use a local secret,
  `services/invitation/tokens.py:67-129`) and
  `core/kms_ops.schedule_cmk_deletion` (tests and a runbook only).
- Rotation hooks: TOTP ciphertext carries a per-row version
  (`users.two_factor_secret_dek_version`, mapped to an expected key by
  `two_factor_service._resolve_dek_alias_for_version`, unknown versions fail
  closed); PII has v1/v2 columns with dual-write, but audit rows cannot be
  backfilled (`workers/pii_hash_backfill.py:18`), pre-transfer summaries read
  only v1 (`services/audit_service.py:530`), and banners compute one hash
  (`services/user_banner.py:276,291`). The audit chain has no key versioning.
- Stored TOTP format: 4-byte length + wrapped DEK blob + 12-byte nonce +
  AES-GCM ciphertext (`two_factor_service.py:3-10`).
- Storage migration decision 9: no deployment carries existing data over; dev,
  preview and ninjin are recreated empty. That covers this cutover too: rows
  made with the public material are discarded, not migrated.
- Tests: moto `mock_aws` backs ~90 KMS tests (`tests/_kms_moto.py`,
  `unit/core/test_kms*`, `security/crypto`, `security/key_rotation`); CI starts
  LocalStack only in the e2e workflow.

## Threat model

What the keyring protects, with keys kept apart from the database:

- **A database dump or DB backup alone** reveals no TOTP secret (each is
  encrypted under a DEK wrapped by the TOTP key) and no raw PII behind the
  keyed hashes; the hashes still reveal equality (same actor, same IP) within
  the dump.
- **A Lustre snapshot** holds no key: the keyring is not on Lustre.
- **Tampering with audit rows** without the audit key breaks the MAC chain.

What it does not protect:

- Other database fields, recordings and anything on Lustre are plaintext at
  rest, as before.
- A backup that captures the whole VM (keyring and database together).
- Code execution as the application, readable process memory, host root, or
  control of Docker: all of them can use or read the keys.
- The chain MAC detects edits and gaps inside the chain but not rollback of the
  whole table or deletion of the newest rows. The weekly archives (storage
  slice 3) help only for closed weeks; independently retained snapshots or
  signed checkpoints are still an unresolved operational requirement
  (storage open decision 7), and the interval since the last archive is
  unprotected.
- Swapping two users' complete TOTP envelopes: the AAD binds purpose and key,
  not the user row (unchanged from today).

## Design

**Keyring file.** JSON, `format: 1`:

```json
{"format": 1,
 "keys": {
   "totp-wrap-2026-09": {"purpose": "totp-wrap", "material": "<base64, 32 bytes>", "created": "2026-09-24"},
   "pii-hmac-2026-09":  {"purpose": "pii-hmac",  "material": "…", "created": "…"},
   "audit-hmac-2026-09":{"purpose": "audit-hmac","material": "…", "created": "…"}}}
```

- Key ids: 1-64 characters of `[a-z0-9-]`, immutable, never reused for other
  material. Purposes are exactly `totp-wrap`, `pii-hmac`, `audit-hmac`.
- Material is always fresh CSPRNG output (`os.urandom(32)`), never derived.
- Selectors (settings, forwarded to every consumer): `KEYRING_FILE`,
  `KEYRING_TOTP_KEY` + `KEYRING_TOTP_KEY_VERSION`, optional
  `KEYRING_TOTP_KEY_OLD` + `_VERSION_OLD`, `KEYRING_PII_KEY`, optional
  `KEYRING_PII_KEY_V2`, `KEYRING_AUDIT_KEY`. Validation: every selector is
  non-empty and present, its key has the selector's purpose, no id is selected
  for two roles, no two entries share material, old key/version come as a
  pair, versions are distinct positive integers. The invitation, 2FA-reset,
  session and JWT secrets stay independent environment secrets.
- The file never enters Git, images or build contexts (`.gitignore`,
  `.dockerignore`).

**Wrapped DEK format.** `header = b"EKR" | 0x01 | len(key_id):u8 | key_id`;
`blob = header | nonce(12) | AESGCM(key).encrypt(nonce, dek, aad=b"echoroo:totp-wrap:" + header)`
with a fresh `os.urandom(12)` nonce, a 32-byte DEK and the full 16-byte tag.
The parser rejects unknown magic or version, a key id outside the allowed
syntax, lengths that do not match, trailing bytes and unknown keys; there is
no legacy-format fallback. Random 96-bit nonces are safe at this volume (one
wrap per 2FA enrolment). **Unwrap takes the expected key id** (from the row
version, as today) and rejects a blob whose authenticated id differs; rewrap
takes an explicit source and target id.

**HMAC.** `hmac.new(material, message, sha256).hexdigest()` over the same
message bytes as today; this equals KMS `GenerateMac` over identical material,
though new deployments use new material. All MAC comparisons use
`hmac.compare_digest`, including audit verification, which uses `!=` today
(`workers/audit_log_export.py:149`, `api/web_v1/audit.py:491`). Known-answer
tests pin the outputs.

**Public-material denylist.** A frozen list of the four digests
`sha256(material)` of the LocalStack-derived keys lives in the code (not
derived from the init script, which will be deleted). Any entry — selected or
not, under any id — whose material matches is refused. This blocks one known
failure; it is not an entropy check.

**Loading, caching and errors.**

- Loaded once per process on first use (and at boot), validated, cached;
  `reset_cache()` exists for tests. Changing the file requires recreating every
  consumer container; there is no hot reload.
- Errors are typed: `KeyringConfigError` (missing/unreadable file, bad JSON,
  failed validation, denylisted material), `KeyringKeyError` (unknown key or
  wrong purpose), `KeyringAuthError` (tag or header check failed). Validation
  runs on use even when boot probes are skipped (`ECHOROO_SKIP_BOOT_CHECKS`).
- Boot: `core/boot_checks` loads the keyring and translates `KeyringConfigError`
  into `BootCheckError`, so the API refuses to start and the worker exits
  (`workers/celery_app.py:338`) in staging and production; development logs.
  `/health/ready` reports `keyring`; the compose healthcheck moves to
  `/health/ready`.
- Caller contract (fault-injection tests for each):

| Caller | On keyring error |
| --- | --- |
| 2FA verify / enrol (`two_factor_service`) | fail closed: login or enrolment fails; never authorises |
| `verify_pii_hash` v2 error | keep the existing fallback to a valid v1 match (`core/kms.py:471`) |
| Invitation email hash (`services/invitation/emails.py:103`) | keep the legacy-HMAC fallback |
| Audit writer | unchanged: the write fails and the request fails, except where callers already treat audit as best-effort |
| API-key IP enforcement (`middleware/api_key_ip_enforcement.py:397`) | audit is best-effort, the deny still happens |
| Login notification (`api/web_v1/auth.py:299`, dispatcher `:116`) | best-effort, never blocks login |
| Audit chain verification (export, verify endpoint) | report failure, never "verified" |

**Provisioning.** `python -m echoroo.scripts.keyring` with three commands:

- `create PATH` writes a new keyring holding one key per purpose, with
  `O_CREAT|O_EXCL|O_NOFOLLOW` and mode 0400 from creation; it refuses an
  existing path.
- `add PATH --purpose P --id ID` takes an exclusive `flock` on `PATH.lock`
  (a second concurrent `add` fails instead of waiting), reads and fully
  validates the current ring, rejects a duplicate id, adds fresh material,
  validates the result, writes it to a temporary file in the same directory
  (`O_EXCL|O_NOFOLLOW`, 0400), fsyncs it, `os.replace`s it over `PATH` and
  fsyncs the directory. An interruption leaves either the old or the new ring,
  never a truncated one or a lost addition; tests inject failures at each step.
- `check PATH` validates and prints ids, purposes, creation dates and material
  fingerprints (never material).

It runs in a dedicated compose service, `keyring-admin` (profile `admin`,
backend image, UID 1000), which mounts the host directory `/etc/echoroo`
read-write at `/keyring` and has no runtime keyring mount, so it works before
any keyring exists. Host directory: `/etc/echoroo`, 0750, owned by
1000:1000; the file is 0400.

**Mounting.** A long-syntax read-only bind with `create_host_path: false`
(compose secrets ignore uid/mode for file sources), at
`/run/secrets/echoroo-keyring.json`, only into `backend`, `worker` and
`worker-cpu`; not beat, frontend or `keyring-admin`. Every mounted consumer
sees every key: an accepted simplification. Separate rings per consumer would
limit what a compromise of one of them exposes.

**Memory and logs.** Master keys stay resident in the process after loading.
Plaintext DEKs (encrypt, decrypt and rewrap) are held in `bytearray`s and
overwritten after use, best effort; Python cannot guarantee zeroisation
because intermediate `bytes` copies exist (as they do today,
`two_factor_service.py:213,263`). Key material, DEKs and TOTP secrets never
appear in logs, exception messages or `repr`; a test asserts this for every
error type. Every process that loads the keyring (API, workers, the `keyring`
CLI) calls `prctl(PR_SET_DUMPABLE, 0)` first: the kernel then writes no core
dump, whether to a file or to a piped collector such as systemd-coredump
(`RLIMIT_CORE` alone is ignored by piped collectors), and same-UID processes
cannot ptrace it. A startup test asserts the flag. The runbook requires the
host's swap to be encrypted or disabled.

**Backup and recovery.**

- Every key addition is backed up offline before its selector is activated.
  Old material is kept for as long as any database backup or archive depends
  on it; deleting an old wrap key after a successful rewrap still breaks
  restores of older DB backups.
- The offline copy is the whole file plus the selector configuration.
- A restore is tested by decrypting one TOTP secret and verifying the audit
  chain against the restored database.
- Irreversible loss is not recovered by generating new keys: every user
  re-enrols 2FA (after a new TOTP key is added), historical PII lookups are
  lost, and the audit chain can no longer be verified or extended verifiably.
  Resetting the audit chain needs the key-epoch design (see *Risks*); until
  then, the verified weekly archives are the remaining evidence and later rows
  are unverified. The runbook describes this separately.

**Activation barrier.** Any change of keyring contents or selectors happens in
a maintenance window: stop every consumer (API, workers), change the file and
the selectors, recreate them all (`docker compose -f compose.dev.yaml up -d
--force-recreate backend worker worker-cpu`), and compare the loaded state
before reopening. `/health/ready` exposes only the `keyring_state` digest, not
key IDs or fingerprints. Each Celery worker answers a custom remote-control
command (`keyring_status`) from its own cache with selectors, TOTP versions,
and key fingerprints. Run the check with `--expected-workers N`, counting one
for each running Celery worker container: development normally has
`worker-cpu` (`N=1`), plus `worker` when the GPU worker runs (`N=2`). The
required count prevents a busy, unreachable, or stale worker from being
omitted from a passing activation. `keyring_activation_check` compares the
API digest with the detailed worker answers; a test starts a worker on an old
ring and asserts the comparison flags it. There is no rolling activation.

```bash
docker compose -f compose.dev.yaml exec backend \
  uv run python -m echoroo.scripts.keyring_activation_check \
  --expected-workers 1
```

**Rotation (what the existing hooks support).**

- TOTP: `add` a key and back the ring up; in a maintenance window select it as
  `KEYRING_TOTP_KEY` with a new version and keep the previous key as `_OLD`;
  run the rewrap script and verify that no row has the old version; in the next
  window unselect `_OLD`. Its material stays in the file, unselected, for as
  long as any database backup depends on it; the single `_OLD` slot is then
  free for the next rotation.
- PII: `add` a key and select it as `KEYRING_PII_KEY_V2` (dual-write).
  Historical lookups keep needing v1 (audit rows cannot be backfilled;
  summaries and banners read v1), so v1 stays selected indefinitely. The
  existing "rotation complete" mode (`ECHOROO_PII_HASH_ROTATION_COMPLETE`,
  `core/kms.py:504`) is removed and rejected by settings validation; a third
  generation needs its own design.
- Audit chain: pinned (decision 3); excluded from rotation and deletion.

## Assumptions

- **No existing ciphertext or MAC needs to survive** (storage decision 9).
- **The dead invitation HMAC and `schedule_cmk_deletion` can be deleted.**
  Reversible from history.
- **One keyring for all consumers is acceptable** (see *Mounting*).

## Decisions taken

| # | Question | Decision (2026-09-24) |
| --- | --- | --- |
| 1 | Where may encryption keys live? | No institutional policy and no institute key service: **a keyring file on the VM**. |
| 2 | Who holds the offline copy? | **The maintainer's password manager.** Whether VM-level backups or snapshots exist is not known yet; a path exclusion does not help against disk or memory snapshots, so before production the runbook requires confirming with the VM provider. If snapshots exist, the keyring lives on a separate virtual disk excluded from them and memory snapshots are disabled; otherwise the risk is recorded as accepted. File-level backups exclude `/etc/echoroo`. |
| 3 | May the audit-chain key stay fixed? | **Yes**, for the lifetime of the data; it is excluded from routine rotation. Recovering from its compromise needs key epochs, which this design does not provide (see *Risks*). |

## Risks

- **Keyring loss**: see *Backup and recovery*. Detection: boot fails, `check`.
- **Keyring captured with the database** (VM backup, copied directory):
  envelope void. Mitigation: decision 2 (exclude `/etc/echoroo` from VM backups).
- **Divergent keyrings across containers** after an edit: prevented by the
  activation barrier; readiness reports what each consumer loaded.
- **Audit-key compromise** cannot be recovered in place: a new key does not
  start a separately verifiable chain (the writer continues from the tail and
  the exporter accepts bootstrap rows only at the chain start,
  `workers/audit_log_export.py:123`). Recovery needs a key-epoch design
  (archive, reset boundary, separate archive names); until then the response
  is to preserve the verified archives and treat later rows as unverified.

## Slices

### 1. Keyring module and CLI, unused

- **Scope** — `core/keyring.py` (format, validation, typed errors, wrap/unwrap
  with expected id, rewrap, HMAC, denylist, cache + reset, secret-free errors
  and reprs), the `keyring` CLI (create/add/check with the atomic, locked
  update contract and failure-injection tests), settings fields (optional, unused), unit tests:
  known-answer HMAC vectors, parser/tamper cases, wrong purpose, shared
  material, selector conflicts, denylist under any id, file-creation flags and
  modes. No boot or health integration yet; nothing calls it.
- **Out of scope** — `core/kms.py`, callers, compose, CI.
- **Depends on** — nothing. **UX preview needed** — no.

### 2. Switch to the keyring

- **Scope** — `core/kms.py` delegates to the keyring (boto3 KMS, `kms_ops`,
  invitation HMAC functions and the alias settings go; key-id settings
  forwarded in compose to backend/worker/worker-cpu); caller error contract
  and constant-time audit comparisons; boot check, `/health/ready`, compose
  healthcheck on `/health/ready`, read-only keyring bind; `rewrap_dek.py` with
  explicit ids; `echoroo.sh` checks keyring settings instead of aliases; the
  e2e workflow provisions a keyring (LocalStack container removed there);
  tests move from moto to a fixture keyring (autouse, per worker), moto and
  the KMS mutation target move to `core/keyring.py`; lints: AWS SDK banned
  everywhere; `.env.example`, `.gitignore`, `.dockerignore`; minimal runbook
  (provision, back up, recover, rotate TOTP, PII v2, audit pin); dev reset +
  reseed (storage decision 9).
  One audit-chain verification shared by the exporter and the verify endpoint
  (`api/web_v1/audit.py:484` today rejects the zero-hash bootstrap rows of a
  fresh database and checks MACs without checking links): bootstrap rows only
  at the chain start, adjacency of `prev_hash`, constant-time comparison.
- **Out of scope** — PII generation three, audit key epochs.
- **Acceptance** — backend suite green without moto; fault-injection tests per
  caller; the verify endpoint accepts a fresh database and rejects a deleted
  interior row; e2e (2FA enrol and login, audit verify) green with no LocalStack;
  dev stack boots only with a provisioned keyring and refuses the public
  material.
  PII "rotation complete" mode removed and its tests rewritten to keep v1
  lookups; `cmk_rotation.md` and `dek_rewrap.md` rewritten for the keyring and
  a superseded notice on every other runbook that still describes AWS KMS.
- **Depends on** — slice 1, decisions 1-3. **UX preview needed** — no.

### 3. Remove LocalStack leftovers

- **Scope** — the LocalStack service and `init-localstack.sh`, the remaining
  docs rewritten (`backup_restore`, `release_readiness`, `storage_cutover`,
  `zero-email-deployment-secret-rotation`, onboarding), `moto` dependency and
  lockfile.
- **Acceptance** — `grep -ri localstack` finds only history; CI green.
- **Depends on** — slice 2. **UX preview needed** — no.

## Review log

| Date | Reviewer | Findings | Resolution |
| --- | --- | --- | --- |
| 2026-09-24 | Astra, design review | Slice 2 not runnable without slice 3's mounts/e2e/reset; threat model unstated; Transit comparison overstated; no domain separation between HMAC keys; embedded key id weakened wrong-key rejection; PII rotation beyond existing hooks; cache/refresh protocol missing; failure behaviour per caller undefined; boot integration unspecified; provisioning/mount procedure; backup/recovery incomplete; audit-key rotation rule; wire-format details; constant-time comparison and KAT; CI/docs scope; open decision 3 reopened storage decision 9 | All accepted: provisioning, mounts, e2e and reset moved into the switch slice; threat model and accepted trade-off written down; purposes per role with selector validation; expected key id on unwrap; PII rotation limited to v2 dual-write; restart-only reload; caller error table with fault-injection tests; typed errors and boot translation; create/add/check CLI and read-only bind; backup/restore/loss procedures; audit key pinned (new open decision 3); wire contract, `compare_digest`, KAT, frozen denylist; scope list extended; reset follows decision 9 |
| 2026-09-24 | Maintainer | Decisions 1-3 | Keyring file; offline copy in the maintainer's password manager, `/etc/echoroo` excluded from any VM backup; audit key fixed |
| 2026-09-24 | Astra, design re-review | Decisions unrecorded; `add` had no safe update contract; provisioning through the backend service inherited the keyring mount; no activation barrier, and retiring `_OLD` was conflated with keeping its material; audit-chain restart unsupported; memory-handling rules missing; PII completion mode and old runbooks still in scope; mount separation and archive checkpoints overstated | All accepted: decisions recorded; locked atomic `add` with failure tests; `keyring-admin` service; maintenance-window activation with loaded-state readiness; unselect `_OLD` after verified rewrap, keep material for backups; audit-key compromise recovery stated as unsupported until key epochs; bytearray DEKs, secret-free errors, no core dumps, encrypted/no swap; completion mode removed, runbooks rewritten in slice 2 |
| 2026-09-24 | Astra, design pass 3 (GO WITH CHANGES, slice 1 may proceed) | Key-loss recovery still promised an audit restart; the verify endpoint differs from the exporter (rejects fresh bootstrap rows, no link check); no way to see what a worker loaded; `RLIMIT_CORE` ignored by piped core collectors; a path exclusion does not stop disk or memory snapshots | All accepted: loss handling states the audit chain cannot be restarted without epochs; one shared verification in slice 2 with acceptance cases; `celery inspect keyring_status` plus a stale-worker test; `PR_SET_DUMPABLE=0` in every keyring process; VM snapshot check before production, separate excluded disk if snapshots exist |
| 2026-09-24 | Astra, slice 1 code review (2 passes) | CLI parser errors echoed user-supplied arguments; ignore patterns missed generated temp/rollback/lock names; HMAC operations accepted a wrapping key; duplicate JSON members silently replaced earlier values; malformed expected MACs raised `TypeError`; plaintext copied before the wiping `try`; failure injection and creation-mode tests too shallow; unknown-key and repr tests did not test what they claimed | All accepted; approved on the second pass |
| 2026-09-24 | Astra, slice 2 code review | Activation check called a non-existent `Inspect.keyring_status()` and passed when a worker did not answer; integration/security doubles returned immutable DEKs; e2e did not enrol 2FA or verify the audit chain; rewrap runbook command incomplete | All accepted: broadcast + required `--expected-workers`; doubles removed in favour of the fixture keyring; `keyring-2fa.spec.ts` (register, enrol, log in with the enrolled secret) and `verify_audit_chain --check-detects-deleted-row` in the e2e workflow; runbook commands corrected. Dev: fresh DB on a provisioned keyring, activation check equal across API and worker, boot refuses public material / wrong selector / missing file |
