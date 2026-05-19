# Phase 0 Research: Seeded Permission E2E Coverage

## Decision: Extend the existing seeded fixture strategy in small browser suites

**Rationale**: The current green baseline already creates the required users,
public/restricted projects, trusted overlay, content rows, and raw API keys. New
suites can reuse this seed state while keeping each surface isolated behind its
own environment gate.

**Alternatives considered**:
- One large all-surfaces suite: rejected because failures would be harder to
  classify and risky media/search cases would slow every permission run.
- Mocked frontend permission tests only: rejected because the remaining gaps are
  integration boundaries between browser session state, BFF routes, and `/api/v1`.

## Decision: Treat `/api/v1` and `/web-api/v1` as separate auth contracts

**Rationale**: `/api/v1` permission checks should use seeded raw API keys. Browser
login and session cookies should be used for UI and BFF checks. This matches the
current green baseline and avoids mixing web JWTs into API-key contract tests.

**Alternatives considered**:
- Reuse web bearer tokens for all API checks: rejected because it does not match
  the documented seeded API key surface.
- Use browser UI for every assertion: rejected because vote/comment semantics are
  primarily API permission behavior and UI controls may not be stable.

## Decision: Data Surfaces excludes media playback and spectrogram assertions

**Rationale**: The current seed creates recording metadata but does not guarantee
an accessible audio object. List/detail visibility can be tested now; byte-level
media and rendered spectrogram behavior belongs to the media slice.

**Alternatives considered**:
- Assert audio playback in data-surfaces: rejected because it would require
  storage fixture work and widen the slice beyond read/detail permission checks.

## Decision: Detection detail remains a limited smoke target

**Rationale**: Dataset and recording list/detail surfaces have stable UI and API
paths. Detection list/detail routes exist, but deep-link detail uses a tag ID
rather than the seeded detection ID, and parts of the detection service still
depend on deferred Phase 14+ annotation tables. Data Surfaces should include
detection only where the current UI/API path is stable, and should not make the
overall suite depend on detection service internals that are outside this slice.

**Alternatives considered**:
- Require successful detection detail for every role immediately: rejected
  because it can fail for reasons unrelated to permission rendering.
- Drop detection entirely: rejected because the roadmap calls out detection read
  coverage; limited smoke keeps the coverage goal visible without overclaiming.

## Decision: Vote/comment tests should be API-primary and serial when mutating

**Rationale**: Vote POST is idempotent replacement for a user's vote, DELETE
mutates shared annotation state, and comments create persistent rows. Running the
suite with `--workers=1`, unique comment bodies, and explicit setup/cleanup
keeps reruns stable.

**Alternatives considered**:
- Parallel mutation matrix over one annotation: rejected because shared state can
  create order-dependent failures.
- Add per-role annotations immediately: deferred until flakiness requires it.

## Decision: Claude review is reserved for higher-risk slices

**Rationale**: Trusted lifecycle, export/search contracts, and media/storage auth
carry higher security and data-integrity risk. Data Surfaces and Vote/Comment
can proceed with normal Codex review unless they expand into those areas.

**Alternatives considered**:
- Review every slice with Claude: rejected as unnecessary overhead for narrow,
  low-risk E2E additions.

## Resolved Clarifications

- **Feature spec source**: `spec.md` is now created for the 007 continuation
  because the directory previously had `plan.md` but no feature spec.
- **Setup script behavior**: `.specify/scripts/bash/setup-plan.sh` would
  overwrite `plan.md`; existing plan content is preserved and extended manually.
- **Additional seed env**: The seeder already includes recording and detection
  IDs in nested project payloads, but the flat `env` payload should emit
  visibility-prefixed `E2E_*_SITE_ID`, `E2E_*_RECORDING_ID`,
  `E2E_*_DETECTION_ID`, and any detection tag ID needed by UI deep links before
  data-surface tests depend on them.
