# Feature Specification: License Master Unification

**Feature Branch**: `012-license-master-unification`
**Created**: 2026-05-26
**Status**: Draft
**Input**: User description: "License Master Unification — Promote the `licenses` table to be the single source of truth for project licenses. Today the project creation form hardcodes four CC license options on the frontend while the admin license master (with full CRUD) ships empty; the two never sync. Convert `projects.license` from an enum string to a FK referencing `licenses.id`, seed the master with the four standard licenses, and have project creation fetch from the master so admin additions appear automatically."

## User Scenarios & Testing *(mandatory)*

<!--
  The three user stories below are ordered by importance. Each is independently
  testable: implementing only the highest-priority story still gives admins a
  workable, even if minimal, license management flow.
-->

### User Story 1 - Admin-added licenses appear in project creation (Priority: P1)

A platform administrator opens the admin license screen, creates a new license (e.g. "CC-BY-ND 4.0"), and clicks save. A team member subsequently opening the "New Project" form sees that new license in the dropdown immediately, without any code change or deployment.

**Why this priority**: This is the headline outcome the user requested. The current system feels broken because licenses managed in the admin UI never reach end users; closing this loop is the entire point of the feature.

**Independent Test**: Sign in as an administrator, add a license through the admin UI, sign out, sign back in as a regular project owner, open the "New Project" form, and confirm the newly added license is in the dropdown and selectable. Submitting the form with that license must successfully create a project whose license matches.

**Acceptance Scenarios**:

1. **Given** the master license list is in its default seeded state, **When** an admin adds a new license through the admin UI and a project owner opens the "New Project" form, **Then** the new license appears in the dropdown alongside the seeded ones, in a stable order.
2. **Given** a project owner has the "New Project" form open with a stale dropdown, **When** they submit a project with a license id that no longer exists (e.g. admin deleted it in another tab), **Then** the system rejects the submission with an actionable error message naming the offending license, rather than silently creating a project with a broken reference.
3. **Given** an admin has hidden or deleted a license through the admin UI, **When** a project owner opens the "New Project" form, **Then** the hidden/deleted license is not offered.

---

### User Story 2 - Existing projects keep their license without manual intervention (Priority: P1)

When the platform is upgraded to use the new license model, every existing project that had a license assigned (CC0, CC-BY, CC-BY-NC, or CC-BY-SA) continues to display that same license in every screen it appeared before. Operators do not have to backfill, re-tag, or notify project owners.

**Why this priority**: Tied for P1 because launching the feature with broken licenses on existing projects would be a worse outcome than not shipping it at all. The change must be invisible to anyone whose project already had a sensible value.

**Independent Test**: Snapshot the license value of every existing project before upgrade. After upgrade, fetch the license string each project reports through the API (or displays in the UI). Every value must match the snapshot exactly, modulo any human-facing wording change documented in this spec.

**Acceptance Scenarios**:

1. **Given** a project created before this change with `license = "CC-BY"`, **When** the upgrade is applied, **Then** the project's license still reports as "CC-BY" (or the equivalent short name from the seeded master) in the project detail screen and any export that previously included it.
2. **Given** the master license list has been customized by an admin (e.g. they renamed "CC0" to "Public Domain" in the admin UI), **When** an upgrade applies the migration, **Then** the admin's existing customization wins — the migration only fills in rows that did not already exist by short name.

---

### User Story 3 - Licenses in use cannot be deleted accidentally (Priority: P2)

An administrator attempts to delete a license that is still attached to one or more projects (or datasets). The system refuses the deletion with a message that names the license, says how many projects (and datasets) depend on it, and explains that they must be reassigned or removed first.

**Why this priority**: P2 because most admin teams will never hit this in normal use, but the alternative — silently allowing the deletion and leaving orphaned references — would corrupt the data model the rest of the feature depends on.

**Independent Test**: Create a project with a specific license, attempt to delete that license through the admin UI, and confirm (a) the deletion is refused, (b) the error message says how many objects are still using the license, and (c) the license remains visible and usable afterwards.

**Acceptance Scenarios**:

1. **Given** at least one project references license X, **When** an admin attempts to delete license X, **Then** the deletion is refused and the admin sees a message that includes the count of projects (and, if applicable, datasets) still using it.
2. **Given** no project and no dataset reference license X, **When** an admin attempts to delete license X, **Then** the deletion succeeds and the license disappears from both admin and project-creation UI.

---

### Edge Cases

- **Stale dropdown after admin edit**: A project owner has the "New Project" form open while an admin renames or deletes a license in another tab. On submit, the system must reject the now-invalid id with a clear, retriable error (not a generic 500).
- **Migration on a database with extra enum values**: If preview/staging environments contain `projects.license` values that are not in the four-license seed list (e.g. due to manual testing), the migration must either fail loudly with a list of unrecognized values, or map them to an "Unknown" placeholder that admins can resolve afterwards — silently dropping the value is not acceptable.
- **Empty master after admin deletes everything**: If an admin somehow deletes every license (including the seeded ones, on the rows that have no projects depending on them), the project creation form must still load without crashing and surface an actionable message ("No licenses available — ask an administrator to add one").
- **License rename mid-flight**: If an admin edits a license name while a user has it selected in an unsubmitted form, the submission should still succeed (id-based, not name-based) and the new project should display the current name on next render.
- **Display name vs short name**: Some users will recognize "CC-BY" but not "Creative Commons Attribution 4.0 International". The user-facing surface should default to the short name with a tooltip or secondary line for the full name, mirroring how the form presents it today.

## Requirements *(mandatory)*

### Functional Requirements

#### Source of Truth

- **FR-001**: The system MUST treat the `licenses` master record set as the single source of truth for the set of licenses a project can be tagged with. No license string may appear in the "New Project" dropdown that is not currently present, undeleted, in the master.
- **FR-002**: The "New Project" form MUST populate its license dropdown by reading the live master at the moment the form is opened, not from a frontend constant or build-time bundle.
- **FR-003**: A newly added admin license MUST appear in the project creation dropdown for any user who opens that form after the admin's save completes, with no additional deployment, cache flush, or service restart.

#### Data Model

- **FR-004**: A project MUST reference its license by a stable identifier that survives renaming the license. (Renaming "CC-BY" to "CC-BY 4.0" in the admin UI must not orphan any project.)
- **FR-005**: The system MUST allow a project to optionally have no license assigned. Creating a project without picking a license, or clearing the license on an existing project, must remain supported with the same UX as today.
- **FR-006**: A license that is referenced by at least one project (or, see FR-008, at least one dataset) MUST NOT be deletable through the admin UI or its API. Any such deletion attempt MUST be refused with an error that names the license and includes the count of dependent projects and datasets.

#### Initial Seed & Migration

- **FR-007**: On first deployment of this feature, the system MUST seed the license master with the four licenses that the project creation form currently offers, using the same short names users see today (CC0, CC-BY, CC-BY-NC, CC-BY-SA). If the master is non-empty when the seed runs (e.g. an admin has already curated it), the seed MUST only fill in rows whose short name is not already present — never overwrite admin edits.
- **FR-008**: The system MUST migrate every existing `projects.license` value to the new identifier-based representation in a single deployment step. After migration, no project may retain a legacy enum-style string value, and no project that had a legacy value may end up with an empty or unknown license.
- **FR-009**: The migration MUST be deterministic: a given legacy enum value always maps to the same seeded license row. The mapping table MUST be documented in the migration so that operators can audit what the upgrade did.
- **FR-010**: If the migration encounters a `projects.license` value that does not match any of the four well-known enum values it knows how to map, it MUST abort with a clear list of the offending values rather than silently dropping or guessing.

#### Datasets

- **FR-011**: This change MUST NOT alter the shape of the existing `datasets.license_id` relationship. Datasets continue to reference the same master that projects now do.
- **FR-012**: When a license is referenced by datasets (in addition to or instead of projects), the delete-protection behavior in FR-006 MUST include the dataset count in the refusal error.
- **FR-013**: The on-delete behavior for dataset-license references MUST be aligned with the new project-license behavior: a license referenced by at least one dataset MUST NOT be deletable, exactly as in FR-006 for projects. The existing "set to null" behavior on the dataset-license link MUST be updated to "refuse delete" during this migration so that the deletion rule is uniform across both project and dataset references. (Rationale: a single deletion rule is simpler for admins to reason about, and it removes any path by which an in-use license can silently disappear from a dataset's record.)

#### Admin UI

- **FR-014**: The admin license CRUD UI MUST continue to function exactly as it does today (create, read, update); only delete gains the dependency check from FR-006. No new admin training material is required for create/read/update.
- **FR-015**: When the admin UI surfaces the delete-protection refusal, the error message MUST be actionable: it MUST tell the admin (a) which license, (b) how many projects depend on it, (c) how many datasets depend on it, and (d) at least one concrete next step (reassign or delete the dependents first).

#### Non-functional

- **FR-016**: Reading the live license master to populate the project creation form MUST NOT add a user-perceivable delay to opening that form. Specifically: the dropdown must be populated within the same time-to-interactive budget the form has today (within roughly one second on a normal connection).
- **FR-017**: The license master read endpoint used by the project creation form MUST be accessible to any authenticated user who is allowed to create a project. It MUST NOT require platform-administrator privileges.

### Key Entities

- **License**: An entry in the master list of acceptable project (and dataset) licenses. Has a stable identifier that does not change on rename, a short name (e.g. "CC-BY") shown in dropdowns, a longer human-readable name (e.g. "Creative Commons Attribution 4.0 International") for tooltips and detail pages, an optional URL to the canonical license text, and an optional administrator-authored description.
- **Project ↔ License relationship**: A project may reference at most one license at a time. The reference is by stable identifier (so the license can be renamed without breaking the project). The reference may also be absent (a project without an assigned license remains supported).
- **Dataset ↔ License relationship**: A dataset may reference at most one license. The reference shape is unchanged, but the on-delete behavior is tightened (FR-013) so that an in-use license cannot be deleted out from under any dataset that still references it — matching the new project rule.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After this feature ships, an admin who adds a new license through the admin UI sees that license offered in the "New Project" dropdown on their very next form open, without any further action. Time from admin save to user-visible availability is under five seconds on a normal connection.
- **SC-002**: Zero existing projects lose their previously-assigned license during the upgrade. Operators who snapshot the license-text-as-rendered-to-users for every project before the upgrade can verify a 100% match afterwards.
- **SC-003**: No project, after the upgrade, references a license that does not exist in the master. The data model offers no path to create such a state on a fresh deployment.
- **SC-004**: Attempts to delete an in-use license result in a refusal with an actionable error in 100% of cases tested across project-only dependency, dataset-only dependency, and mixed dependency.
- **SC-005**: The project creation form continues to load and become interactive within its current time budget (no measurable regression). Specifically, the additional time spent fetching the license master is below 200 milliseconds at the 95th percentile on a normal connection.
- **SC-006**: The release ships with zero hardcoded license strings remaining anywhere in the user-facing surface — the admin UI, the project creation form, and any related help text all derive license names from the master.

## Assumptions

- **A-001**: The four currently-hardcoded licenses (CC0, CC-BY, CC-BY-NC, CC-BY-SA) cover 100% of existing projects. Validated separately by inspecting the production / preview snapshot before migration; if other values are found, FR-010 governs the response.
- **A-002**: The existing license master schema (id, short_name, name, url, description) is sufficient. No new columns are required for v1. License-text localization (different display name per locale) is out of scope.
- **A-003**: License lifecycle does not need a "soft delete" or archival state. The combination of (a) admins can rename, (b) deletes are blocked when dependencies exist, and (c) successful deletes are immediate removals, is sufficient.
- **A-004**: Project creation traffic is low enough that the master can be fetched live on every form open without a caching layer. If profiling shows otherwise post-launch, caching is a follow-up, not a launch blocker.
- **A-005**: This is a forward-only schema migration, following the precedent set by spec/011 step 11. Operators cannot downgrade past this point without restoring from backup; the spec assumes that posture is acceptable given the pre-launch project status documented in memory.
- **A-006**: Existing administrative tooling (system settings, admin permissions) is sufficient. No new admin role is required.

## Out of Scope

- Per-project custom licenses authored by project owners (no "I want my own license text" UX in v1).
- Localization of license names — display values come straight from the master and are not translated.
- License versioning (e.g. CC-BY 3.0 vs 4.0 as distinct rows) is supported by simply adding rows; no automatic upgrade between versions.
- Bulk re-licensing across projects (e.g. "change every CC-BY project to CC-BY-SA") — administrators perform such operations one project at a time using existing tools.
- Changing how datasets reference licenses, beyond the FR-013 clarification.
