# Data Model: Seeded Permission E2E Coverage

## SeededUser

Represents a local E2E actor.

Fields:
- `role`: `owner | admin | member | viewer | nonmember | trusted | trusted_lifecycle`
- `email`: login email emitted as `E2E_<ROLE>_EMAIL`
- `user_id`: UUID emitted as `E2E_<ROLE>_USER_ID`
- `password`: shared local password emitted as `E2E_PASSWORD`
- `totp_secret_env`: top-level metadata naming `E2E_<ROLE>_TOTP_SECRET`; the raw secret is emitted only in `env`
- `api_key_env`: top-level API key metadata naming `E2E_<ROLE>_API_KEY`; the raw key is emitted only in `env`

Validation rules:
- All seeded users must be present before any suite runs.
- API keys are local-only secrets and must be regenerated through the seeder.
- The latest seed JSON must be used for test execution.
- Seeder reruns reset fixture-user 2FA failure/lockout Redis keys on a best-effort basis.

## SeededProject

Represents one permission target project.

Fields:
- `visibility`: `public | restricted`
- `project_id`: UUID emitted as `E2E_<VISIBILITY>_PROJECT_ID`
- `project_name`: emitted as `E2E_<VISIBILITY>_PROJECT_NAME`
- `site_id`: UUID to emit as `E2E_<VISIBILITY>_SITE_ID`
- `dataset_id`: UUID emitted as `E2E_<VISIBILITY>_DATASET_ID`
- `dataset_name`: emitted as `E2E_<VISIBILITY>_DATASET_NAME`
- `recording_id`: UUID to emit as `E2E_<VISIBILITY>_RECORDING_ID`
- `clip_id`: UUID emitted as `E2E_<VISIBILITY>_CLIP_ID`
- `detection_id`: UUID to emit as `E2E_<VISIBILITY>_DETECTION_ID`
- `detection_tag_id`: optional tag identifier for detection UI detail routes
- `annotation_id`: UUID emitted as `E2E_<VISIBILITY>_ANNOTATION_ID`
- `search_session_id`: UUID emitted as `E2E_<VISIBILITY>_SEARCH_SESSION_ID`
- `exportable_search_session_id`: UUID emitted as
  `E2E_<VISIBILITY>_EXPORTABLE_SEARCH_SESSION_ID`
- `trusted_overlay_id`: UUID emitted as `E2E_<VISIBILITY>_TRUSTED_OVERLAY_ID`

Relationships:
- A seeded project has one site, one dataset, one recording, one clip, one
  detection, and one annotation for stable smoke coverage.
- Owner owns both projects. Admin, member, and viewer are project members.
- Trusted has active trusted overlays but no project membership.
- Trusted lifecycle has disposable restricted-project lifecycle overlays but no
  project membership.
- Nonmember has no project membership.
- Each project has one completed search session for API-primary search/export
  permission checks.

Validation rules:
- Public and restricted projects must both exist.
- Project names and content names must be deterministic enough for UI assertions.
- Restricted project config intentionally allows voting and comments for current
  baseline expectations.

## SeededContentFixture

Represents one content chain per project.

Fields:
- `site_id`
- `dataset_id`
- `recording_id`
- `embedding_id`
- `clip_id`
- `detection_id`
- `annotation_id`
- `dataset_name`
- `recording_filename`
- `detection_taxon_id`

Relationships:
- Site belongs to project.
- Dataset belongs to site/project.
- Recording belongs to dataset/site.
- Embedding belongs to recording and uses the seeded search model name.
- Clip belongs to recording.
- Detection belongs to recording/project.
- Annotation belongs to detection.

Validation rules:
- Data-surface tests may assert list/detail presence.
- Media tests may assume the seeded recording path points to the deterministic
  WAV fixture after the latest seed command has completed.
- Media tests may assume the seeded clip spans the deterministic WAV fixture
  interval from `1.0` to `2.5` seconds.
- Detection detail tests may not assume detection UUID is the UI route
  identifier; use a seeded tag ID or derive one from a stable API response.

## SeededMediaFixture

Represents the deterministic audio object backing each seeded recording.

Fields:
- `recording_path`: `e2e/{prefix}/{visibility}/fixture.wav`
- `duration`: `12.5`
- `samplerate`: `48000`
- `channels`: `2`
- `bit_depth`: `16`
- `content_type`: `audio/wav`
- `sha256`: deterministic digest emitted into the `Recording.hash` field

Relationships:
- One media fixture path backs the public seeded recording.
- One media fixture path backs the restricted seeded recording.
- The path is both relative to `AUDIO_ROOT` and the S3 object key used by
  `AudioService.ensure_file_local()`.

Validation rules:
- Seeder writes the fixture idempotently to local S3/LocalStack when available.
- Seeder falls back to writing below `AUDIO_ROOT` only when S3 fixture seeding is
  unavailable.
- Media tests assert bytes and content type for recording and clip media
  endpoints, not exact waveform contents.
- Dataset audio ZIP tests assert the expected archive entry and inflated WAV
  `RIFF` bytes for allowed role/visibility `include_audio=true` exports.

## SeededClipFixture

Represents the stable clip created inside each seeded recording.

Fields:
- `clip_id`: UUID emitted as `E2E_<VISIBILITY>_CLIP_ID`
- `recording_id`: parent seeded recording UUID
- `start_time`: `1.0`
- `end_time`: `2.5`
- `note`: deterministic fixture note

Relationships:
- One seeded clip belongs to the public seeded recording.
- One seeded clip belongs to the restricted seeded recording.

Validation rules:
- Clip API-primary media tests assert `/audio`, `/spectrogram`, and `/download`
  status/content type/non-empty bytes.
- Clip browser UI tests assert session BFF list/detail loading plus tokenized
  preview spectrogram, detail spectrogram, and playback URLs.

## VoteCommentState

Represents mutation state on a seeded annotation.

Fields:
- `annotation_id`
- `vote`: `agree | disagree | unsure` depending on API schema
- `comment_body`
- `actor_role`
- `project_visibility`

State transitions:
- No vote -> POST vote -> vote exists.
- Existing vote -> POST vote -> vote is replaced.
- Existing vote -> DELETE vote -> no vote for that actor.
- No comment -> POST comment -> comment is appended.

Validation rules:
- Comment bodies must be unique per test run.
- DELETE vote tests must either restore state or be isolated in a serial block.
- Tests must not rely on comments being absent at the start of a rerun.
- Trusted vote/comment tests assert authorization outcome only; source-badge
  classification is not part of this slice.

## SeededSearchSession

Represents one completed, storage-free search session per seeded project.

Fields:
- `search_session_id`
- `project_id`
- `user_id`
- `name`
- `status`: `completed`
- `model_name`
- `result_count`: `0`
- `confirmed_count`: `0`
- `rejected_count`: `0`
- `celery_job_id`: `null`
- `reference_audio_keys`: `null`

Relationships:
- Search session belongs to the seeded project.
- Search session is owned by the seeded owner user.
- Search session references seeded project/dataset parameters only; it does not
  seed storage-backed result files or reference audio.

Validation rules:
- Export/Search tests may assert list/detail visibility, CSV status/content
  type, dataset ZIP shape for `include_audio=false`, and storage-free
  `export-recordings` / `reference-audio` permission guard boundaries.
- `export-recordings` guard tests assert allowed callers receive
  `"Session has no results to export"` and denied callers receive 403.
- `reference-audio/0` guard tests assert allowed callers receive
  `"Reference audio source index 0 not found"` and denied callers receive 403.
- Export/Search tests must not assert broader CSV row content or consume
  unrelated streaming export bodies until the corresponding fixtures exist.

## SeededExportableSearchSession

Represents one completed search session per seeded project with a deterministic
single-result payload for `export-recordings` CSV success coverage.

Fields:
- `exportable_search_session_id`
- `project_id`
- `user_id`
- `name`
- `status`: `completed`
- `model_name`: `e2e-seeded-model`
- `result_count`: `1`
- `confirmed_count`: `0`
- `rejected_count`: `0`
- `results`: one `BatchSearchResponse`-shaped result keyed by a deterministic
  UUID-shaped species key
- `reference_audio_keys`: one deterministic S3 object key for
  `e2e/{prefix}/{visibility}/reference-audio-0.wav`

Relationships:
- Exportable search session belongs to the seeded project.
- Exportable search session is owned by the seeded owner user.
- Exportable search session points at the seeded dataset and recording through
  `parameters` and `results`.
- The result match references the seeded deterministic `Embedding` row for the
  same recording and model name.
- The reference audio key points at an S3-backed deterministic WAV fixture; the
  route reads this object directly through S3 rather than `AUDIO_ROOT`.

Validation rules:
- Export/Search tests may consume the owner `export-recordings` CSV body for
  the exportable session and assert the header, one seeded recording row,
  species labels, and `1.0000` aggregate values.
- Export/Search tests may stream the owner `reference-audio/0` response for the
  exportable session and assert full `200` audio bytes plus `206` Range bytes.
- Exportable sessions must not replace the storage-free sessions used for the
  403/404 guard checks.
- Broader multi-row/multi-role CSV body assertions and multi-role dataset audio
  ZIP bodies remain future scope.

## TrustedLifecycleState

Represents disposable trusted overlay rows used for lifecycle mutation coverage.

Fields:
- `trusted_lifecycle_user_id`: emitted as `E2E_TRUSTED_LIFECYCLE_USER_ID`
- `trusted_lifecycle_email`: emitted as `E2E_TRUSTED_LIFECYCLE_EMAIL`
- `trusted_lifecycle_api_key`: emitted as `E2E_TRUSTED_LIFECYCLE_API_KEY`
- `active_overlay_id`: emitted as `E2E_RESTRICTED_TRUSTED_LIFECYCLE_OVERLAY_ID`
- `expired_overlay_id`: emitted as `E2E_RESTRICTED_TRUSTED_EXPIRED_OVERLAY_ID`

Relationships:
- Lifecycle user is authenticated but has no project membership.
- Active lifecycle overlay belongs to the restricted project and is reset by the
  seeder before each lifecycle run.
- Expired lifecycle overlay belongs to the restricted project and is used only
  for status-filter read coverage.
- Baseline trusted overlays for `trusted` remain immutable and separate from
  lifecycle mutations.

Validation rules:
- Lifecycle tests may PATCH/DELETE only the disposable active lifecycle overlay.
- Lifecycle tests must not mutate `E2E_PUBLIC_TRUSTED_OVERLAY_ID` or
  `E2E_RESTRICTED_TRUSTED_OVERLAY_ID`.
- Lifecycle tests intentionally leave the disposable active overlay revoked; run
  the seeder before rerunning the trusted suite.
- Invitation accept/re-grant activation requires signed invite token access and
  remains future scope.

## E2ESuiteGate

Represents a suite-level execution guard.

Fields:
- `enabled_env`: e.g. `E2E_DATA_SURFACES_ENABLED`
- `required_env`: list of required seed variables
- `command`: Playwright command used to run the suite

Validation rules:
- Disabled suites must skip with a clear message.
- Missing seed env must skip with a clear message that references the seeder.
