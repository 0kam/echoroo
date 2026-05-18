# Feature Specification: Seeded Permission E2E Coverage

**Feature Branch**: `007-permission-test-coverage`
**Created**: 2026-05-15
**Status**: US1/US2/US3 plus Trusted Overlay lifecycle, Export/Search API-primary plus Dataset ZIP plus Search storage gate guards plus Export-recordings success CSV, and Media plus Clip API-primary complete
**Input**: Roadmap continuation from `specs/007-permission-test-coverage/e2e-roadmap.md`

## User Scenarios & Testing

### User Story 1 - Data Surface Permission Confidence (Priority: P1)

A maintainer can run seeded browser tests that prove project data pages expose
only the allowed datasets, recordings, detections, and public explore details
for each role and project visibility.

**Why this priority**: Data read access is the broadest user-facing permission
surface and must stay green before launch.

**Independent Test**: Run the seeded data-surfaces Playwright suite after
seeding local fixtures. The suite passes while leaving media playback assertions
to the dedicated Media suite.

**Acceptance Scenarios**:

1. **Given** seeded public and restricted projects, **When** each seeded role
   visits dataset, recording, detection, and explore surfaces, **Then** allowed
   users see the seeded content and denied users see an explicit denial or no
   leaked private content.
2. **Given** a public guest explore flow, **When** the guest views public project
   list/detail, **Then** owner email and private project metadata are not
   rendered.

For this slice, private metadata means owner email, non-public member/trusted
user email, raw API key values, TOTP secrets, restricted project names in public
guest lists, and storage object paths.

---

### User Story 2 - Vote and Comment Permission Confidence (Priority: P1)

A maintainer can run seeded API-backed browser tests that make vote and comment
authorization explicit for owner, admin, member, viewer, nonmember, and trusted
users across public and restricted projects.

**Why this priority**: Vote/comment permissions are mutable and were previously
covered only as broad smoke checks.

**Independent Test**: Run the seeded vote-comment Playwright suite with
`--workers=1` after seeding local fixtures.

**Acceptance Scenarios**:

1. **Given** each seeded role has a raw API key, **When** the role calls
   annotation vote and comment endpoints through `/api/v1`, **Then** the status
   code matches the canonical permission expectation for the project visibility.
2. **Given** a mutating vote/comment test, **When** the suite is rerun, **Then**
   idempotent vote replacement and unique comment bodies keep the run isolated.

---

### User Story 3 - Risky Surface Roadmap (Priority: P2)

A maintainer can continue the same seeded fixture strategy into trusted overlay,
export/search, and media coverage with explicit review and verification gates.

**Why this priority**: These surfaces carry higher security, data integrity, and
storage risk and need planned sequencing before implementation.

**Independent Test**: Each future suite has its own enable flag, seed needs, and
completion gate documented before code changes begin.

**Acceptance Scenarios**:

1. **Given** a future trusted overlay lifecycle suite, **When** it mutates trusted
   users, **Then** it uses disposable rows or resets state instead of destroying
   the baseline overlay.
2. **Given** future export/search/media suites, **When** their implementation
   touches contracts, storage, or media auth, **Then** a bounded Claude review is
   requested before finalizing.

### Edge Cases

- The latest seed JSON must be exported before each run because the seeder
  rotates TOTP secrets, security stamps, and API keys.
- `/api/v1` checks must use seeded raw API keys; browser JWT bearer tokens are
  reserved for `/web-api/v1` routes that explicitly accept them.
- Vote/comment mutations must avoid order coupling. Use serial mode only when a
  test intentionally depends on prior mutation state.
- Data surface tests must not assert successful audio or spectrogram rendering;
  that belongs to the media slice.
- Public project tests must distinguish intentional public overlays from role
  membership permissions.

## Requirements

### Functional Requirements

- **FR-001**: The seeded fixture flow MUST emit all environment variables needed
  by data-surface and vote/comment E2E suites.
- **FR-002**: Data-surface E2E tests MUST cover dataset list/detail, recording
  list/detail, detection list/detail where stable, and public explore list/detail.
- **FR-003**: Public guest data-surface tests MUST assert that owner email and
  private metadata are not leaked.
- **FR-004**: Vote/comment E2E tests MUST cover GET, POST, and DELETE vote
  behavior and GET/POST comment behavior through `/api/v1`.
- **FR-005**: Programmatic `/api/v1` checks MUST authenticate with seeded raw API
  keys, not web session JWTs.
- **FR-006**: Browser/session checks MUST use UI login and `/web-api/v1` session
  behavior for authenticated role-based UI checks.
- **FR-007**: Each new suite MUST be gated by an explicit environment variable
  and skip with a clear message when disabled or missing seed values.
- **FR-008**: Each phase MUST pass seed, static checks, the new E2E suite, and
  the existing seeded matrix and feature suites before being considered done.
- **FR-009**: Trusted overlay, export/search, and media slices MUST receive a
  bounded Claude review when they introduce lifecycle mutation, contract, storage,
  or media-auth changes.

### Key Entities

- **Seeded User**: One of owner, admin, member, viewer, nonmember, or trusted,
  with email, password, TOTP secret, user ID, and raw API key.
- **Seeded Project**: Public or restricted project with visibility-specific
  permission behavior, content rows, and trusted overlay.
- **Seeded Content Fixture**: Site, dataset, recording, clip, detection, and annotation
  rows used by browser and API E2E suites.
- **Seeded API Key**: Local-only raw secret emitted in seed JSON and used for
  `/api/v1` permission checks.
- **E2E Suite Gate**: Environment flag plus required seed variables that decides
  whether a seeded suite executes.

## Success Criteria

### Measurable Outcomes

- **SC-001**: `seeded-data-surfaces.spec.ts` passes locally with `--workers=1`.
- **SC-002**: `seeded-vote-comment.spec.ts` passes locally with `--workers=1`.
- **SC-003**: Existing `seeded-permissions-matrix.spec.ts` remains green.
- **SC-004**: Existing `seeded-feature-permissions.spec.ts` remains green.
- **SC-005**: Python static/type checks for the seeder and TypeScript/Svelte
  static/type checks for changed E2E files pass.
- **SC-006**: The roadmap remains current after each completed slice, including
  verified commands and residual risk notes.
