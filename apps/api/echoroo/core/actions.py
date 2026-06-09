"""Aggregated Action catalog for Phase 3 path operations (spec FR-008a).

Every FastAPI path operation MUST register an :class:`Action` in the global
``ACTIONS`` catalog so the Stage-1 permission gate can look up the required
permission without each endpoint re-implementing the decision logic.

This module is the **single aggregation point** for Phase 3 endpoint Actions.
Routers import the ``*_ACTION`` module variables defined here and pass them to
``Depends(check_action(...))``. New endpoints should register their Action in
this module unless there is a strong locality reason (see audit.py for one
such exception).

Spec references (Rev.3.2):
    FR-008  / FR-008a / FR-008b  — gate algorithm + Action contract
    FR-009  — Permission enum
    FR-010  — Canonical Matrix

Authentication-only or list endpoints (no central Permission gate):
  * POST /projects                    — project.create (any authenticated user)
  * POST /invitations/accept          — invitation.accept (token validation in service)
  * POST /invitations/decline         — invitation.decline_by_recipient (token validation)
  * GET  /projects                    — project.list (no project_id; the service
    layer iterates candidate projects and applies the per-row Permission filter
    individually, so the central Stage-1 gate cannot evaluate it).
These endpoints rely on the FastAPI auth dependency only and are NOT registered
in ``ACTIONS``. Add an entry here if a Permission gate is introduced later.

Out-of-scope (handled elsewhere):
  * Existing audit endpoint Actions live in ``echoroo/api/web_v1/audit.py`` and
    are NOT migrated here in this task. A future task may consolidate them.
  * Superuser-only / platform-scope Actions (e.g. ``project.restore``,
    ``platform.audit_log.read``) are added in subsequent phases.
"""
from __future__ import annotations

from echoroo.core.permissions import Action, Permission, register_action

# =============================================================================
# Project (web_v1/projects/_*)
# =============================================================================

PROJECT_GET_ACTION: Action = register_action(
    Action(
        name="project.get",
        required_permission=Permission.VIEW_PROJECT_METADATA,
        is_mutating=False,
    )
)

PROJECT_UPDATE_ACTION: Action = register_action(
    Action(
        name="project.update",
        required_permission=Permission.EDIT_PROJECT,
        is_mutating=True,
    )
)

PROJECT_DELETE_ACTION: Action = register_action(
    Action(
        name="project.delete",
        required_permission=Permission.DELETE_PROJECT,
        is_mutating=True,
    )
)

PROJECT_TRANSFER_OWNERSHIP_ACTION: Action = register_action(
    Action(
        name="project.transfer_ownership",
        required_permission=Permission.TRANSFER_OWNERSHIP,
        is_mutating=True,
    )
)

PROJECT_RESTRICTED_CONFIG_UPDATE_ACTION: Action = register_action(
    Action(
        name="project.restricted_config.update",
        required_permission=Permission.EDIT_PROJECT,
        is_mutating=True,
    )
)

PROJECT_LICENSE_UPDATE_ACTION: Action = register_action(
    Action(
        name="project.license.update",
        required_permission=Permission.MANAGE_LICENSE,
        is_mutating=True,
    )
)

PROJECT_LICENSE_HISTORY_ACTION: Action = register_action(
    Action(
        name="project.license.history",
        required_permission=Permission.VIEW_PROJECT_METADATA,
        is_mutating=False,
    )
)

PROJECT_MEMBER_LIST_ACTION: Action = register_action(
    Action(
        name="project.member.list",
        required_permission=Permission.MANAGE_MEMBERS,
        is_mutating=False,
    )
)

PROJECT_MEMBER_INVITE_ACTION: Action = register_action(
    Action(
        name="project.member.invite",
        required_permission=Permission.MANAGE_MEMBERS,
        is_mutating=True,
    )
)

PROJECT_MEMBER_REMOVE_ACTION: Action = register_action(
    Action(
        name="project.member.remove",
        required_permission=Permission.MANAGE_MEMBERS,
        is_mutating=True,
    )
)

PROJECT_MEMBER_UPDATE_ROLE_ACTION: Action = register_action(
    Action(
        name="project.member.update_role",
        required_permission=Permission.MANAGE_MEMBERS,
        is_mutating=True,
    )
)


# =============================================================================
# Trusted overlay management (Phase 10 / T510, FR-014 / FR-046 / FR-050)
# =============================================================================

PROJECT_TRUSTED_LIST_ACTION: Action = register_action(
    Action(
        name="project.trusted.list",
        # Phase 10 Batch 2 Round 2 fix (致命 1):
        # Per ``contracts/trusted.yaml`` GET list is Owner / Admin. The
        # Canonical Matrix (spec L425) restricts ``MANAGE_TRUSTED`` to
        # Owner only because INVITE / PATCH / DELETE are Owner-exclusive
        # (FR-050). To let Admin enumerate while keeping mutation
        # endpoints Owner-only we gate the read with ``MANAGE_MEMBERS``
        # (Owner + Admin per the matrix); the mutating actions below
        # keep ``MANAGE_TRUSTED`` so an Admin cannot escalate.
        required_permission=Permission.MANAGE_MEMBERS,
        is_mutating=False,
    )
)

PROJECT_TRUSTED_INVITE_ACTION: Action = register_action(
    Action(
        name="project.trusted.invite",
        required_permission=Permission.MANAGE_TRUSTED,
        is_mutating=True,
    )
)

PROJECT_TRUSTED_UPDATE_ACTION: Action = register_action(
    Action(
        name="project.trusted.update",
        required_permission=Permission.MANAGE_TRUSTED,
        is_mutating=True,
    )
)

PROJECT_TRUSTED_REVOKE_ACTION: Action = register_action(
    Action(
        name="project.trusted.revoke",
        required_permission=Permission.MANAGE_TRUSTED,
        is_mutating=True,
    )
)


# =============================================================================
# Detection / Annotation / Tag / Upload / Custom Model / Recording
# =============================================================================

DETECTION_LIST_ACTION: Action = register_action(
    Action(
        name="detection.list",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

DETECTION_GET_ACTION: Action = register_action(
    Action(
        name="detection.get",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

DETECTION_EXPORT_CSV_ACTION: Action = register_action(
    Action(
        name="detection.export_csv",
        required_permission=Permission.EXPORT,
        is_mutating=False,
    )
)

DETECTION_EXPORT_ML_DATASET_ACTION: Action = register_action(
    Action(
        name="detection.export_ml_dataset",
        required_permission=Permission.EXPORT,
        is_mutating=True,
    )
)

DETECTION_CREATE_ACTION: Action = register_action(
    Action(
        name="detection.create",
        required_permission=Permission.ANNOTATE,
        is_mutating=True,
    )
)

DETECTION_CONFIRM_ACTION: Action = register_action(
    Action(
        name="detection.confirm",
        required_permission=Permission.ANNOTATE,
        is_mutating=True,
    )
)

DETECTION_REJECT_ACTION: Action = register_action(
    Action(
        name="detection.reject",
        required_permission=Permission.ANNOTATE,
        is_mutating=True,
    )
)

DETECTION_CHANGE_SPECIES_ACTION: Action = register_action(
    Action(
        name="detection.change_species",
        required_permission=Permission.ANNOTATE,
        is_mutating=True,
    )
)

DETECTION_DELETE_ACTION: Action = register_action(
    Action(
        name="detection.delete",
        required_permission=Permission.EDIT_PROJECT,
        is_mutating=True,
    )
)

ANNOTATION_VOTE_LIST_ACTION: Action = register_action(
    Action(
        name="annotation_vote.list",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

ANNOTATION_VOTE_CREATE_ACTION: Action = register_action(
    Action(
        name="annotation_vote.create",
        required_permission=Permission.VOTE,
        is_mutating=True,
    )
)

ANNOTATION_COMMENT_LIST_ACTION: Action = register_action(
    Action(
        name="annotation_comment.list",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

ANNOTATION_COMMENT_CREATE_ACTION: Action = register_action(
    Action(
        name="annotation_comment.create",
        required_permission=Permission.COMMENT,
        is_mutating=True,
    )
)

TAG_CREATE_ACTION: Action = register_action(
    Action(
        name="tag.create",
        required_permission=Permission.CREATE_TAG,
        is_mutating=True,
    )
)

TAG_UPDATE_ACTION: Action = register_action(
    Action(
        name="tag.update",
        required_permission=Permission.EDIT_PROJECT,
        is_mutating=True,
    )
)

TAG_DELETE_ACTION: Action = register_action(
    Action(
        name="tag.delete",
        required_permission=Permission.EDIT_PROJECT,
        is_mutating=True,
    )
)

UPLOAD_CREATE_ACTION: Action = register_action(
    Action(
        name="upload.create",
        required_permission=Permission.UPLOAD,
        is_mutating=True,
    )
)

CUSTOM_MODEL_TRAIN_ACTION: Action = register_action(
    Action(
        name="custom_model.train",
        required_permission=Permission.TRAIN_MODEL,
        is_mutating=True,
    )
)

CUSTOM_MODEL_LIST_ACTION: Action = register_action(
    Action(
        name="custom_model.list",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

CUSTOM_MODEL_GET_ACTION: Action = register_action(
    Action(
        name="custom_model.get",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

CUSTOM_MODEL_DELETE_ACTION: Action = register_action(
    Action(
        name="custom_model.delete",
        required_permission=Permission.EDIT_PROJECT,
        is_mutating=True,
    )
)

RECORDING_LIST_ACTION: Action = register_action(
    Action(
        name="recording.list",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

RECORDING_MEDIA_ACTION: Action = register_action(
    Action(
        name="recording.media",
        required_permission=Permission.VIEW_MEDIA,
        is_mutating=False,
    )
)

RECORDING_UPDATE_ACTION: Action = register_action(
    Action(
        name="recording.update",
        required_permission=Permission.MANAGE_DATASET,
        is_mutating=True,
    )
)

RECORDING_DELETE_ACTION: Action = register_action(
    Action(
        name="recording.delete",
        required_permission=Permission.MANAGE_DATASET,
        is_mutating=True,
    )
)

SITE_LIST_ACTION: Action = register_action(
    Action(
        name="site.list",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

SITE_GET_ACTION: Action = register_action(
    Action(
        name="site.get",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

SITE_CREATE_ACTION: Action = register_action(
    Action(
        name="site.create",
        required_permission=Permission.MANAGE_SITE,
        is_mutating=True,
    )
)

SITE_UPDATE_ACTION: Action = register_action(
    Action(
        name="site.update",
        required_permission=Permission.MANAGE_SITE,
        is_mutating=True,
    )
)

SITE_DELETE_ACTION: Action = register_action(
    Action(
        name="site.delete",
        required_permission=Permission.MANAGE_SITE,
        is_mutating=True,
    )
)


# =============================================================================
# Phase 11 / T630 — superuser admin endpoints (FR-034 / FR-036 / FR-111)
# =============================================================================
#
# The two looser-override mutations are *project-scope* actions (a project_id
# is required to load the override row and write a project_audit_log entry),
# but the Stage-1 gate also short-circuits them through
# ``SUPERUSER_PROJECT_SCOPE_ALLOWLIST`` (FR-008b) so a superuser without an
# explicit Permission cell still passes. ``required_permission`` is therefore
# set to a sentinel value the matrix never grants outside the allowlist
# branch — non-superusers always fail closed.

PROJECT_TAXON_OVERRIDE_APPROVE_ACTION: Action = register_action(
    Action(
        name="project.taxon_override.approve_looser",
        # Outside the SUPERUSER_PROJECT_SCOPE_ALLOWLIST short-circuit (FR-008b),
        # this approval is reserved to superusers; ``EDIT_PROJECT`` is the
        # closest matrix cell (Owner-only) so a non-superuser caller still
        # fails the Permission check.
        required_permission=Permission.EDIT_PROJECT,
        is_mutating=True,
    )
)

PROJECT_TAXON_OVERRIDE_REJECT_ACTION: Action = register_action(
    Action(
        name="project.taxon_override.reject_looser",
        required_permission=Permission.EDIT_PROJECT,
        is_mutating=True,
    )
)

# Phase 12 / T702 — superuser-only project lifecycle (FR-061 / FR-062). Both
# actions are project-scope (a project_id is required to lock the row and
# write a project_audit_log entry) but they MUST NEVER be reachable via the
# normal Matrix path — an Owner who happens to satisfy the nominal
# ``EDIT_PROJECT`` permission must NOT be able to archive their own project.
# Phase 12 R1 致命 C1 fix: we mark both actions ``is_superuser_only=True``
# so :func:`echoroo.core.permissions.is_allowed` Step 0c hard-fails any
# non-superuser caller before the Matrix check is consulted.
# ``SUPERUSER_PROJECT_SCOPE_ALLOWLIST`` (FR-008b) provides the positive
# branch for superusers via Step 0b. The ``required_permission`` slot
# below is a sentinel that would only be evaluated if both Step 0b and
# Step 0c were bypassed — neither happens in practice.
PROJECT_ARCHIVE_ACTION: Action = register_action(
    Action(
        name="project.archive",
        required_permission=Permission.EDIT_PROJECT,
        is_mutating=True,
        is_superuser_only=True,
    )
)

PROJECT_RESTORE_ACTION: Action = register_action(
    Action(
        name="project.restore",
        required_permission=Permission.EDIT_PROJECT,
        is_mutating=True,
        is_superuser_only=True,
    )
)


# IUCN force-resync is platform-scope: there is no project_id parameter and
# the Celery task rewrites the global ``taxon_sensitivity`` table. We mark
# the action ``is_platform_scope=True`` so :func:`is_allowed` routes it
# through the Step-0a superuser-only branch.
PLATFORM_IUCN_FORCE_RESYNC_ACTION: Action = register_action(
    Action(
        name="platform.iucn.force_resync",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)


# =============================================================================
# Phase 15 Batch 5a — Superuser CRUD admin endpoints (FR-111 / FR-072 / FR-084)
# =============================================================================
#
# These platform-scope actions back the ``/web-api/v1/admin/superusers/*``
# endpoints. All carry ``is_superuser_only=True`` so the Step -1 universal
# api_key veto in :func:`echoroo.core.permissions.is_allowed` denies any
# API-key principal regardless of its scopes (FR-084 PR-007). Cookie /
# JWT session callers fall through to the Step 0a branch which permits
# only authenticated superusers.

SUPERUSER_LIST_ACTION: Action = register_action(
    Action(
        name="superuser.list",
        required_permission=None,
        is_mutating=False,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

SUPERUSER_ADD_ACTION: Action = register_action(
    Action(
        name="superuser.add",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

SUPERUSER_REVOKE_ACTION: Action = register_action(
    Action(
        name="superuser.revoke",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

SUPERUSER_APPROVAL_REQUEST_LIST_ACTION: Action = register_action(
    Action(
        name="superuser.approval.list",
        required_permission=None,
        is_mutating=False,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

SUPERUSER_APPROVE_REQUEST_ACTION: Action = register_action(
    Action(
        name="superuser.approval.approve",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

SUPERUSER_REJECT_REQUEST_ACTION: Action = register_action(
    Action(
        name="superuser.approval.reject",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

SUPERUSER_BREAK_GLASS_ENTER_ACTION: Action = register_action(
    Action(
        name="superuser.break_glass.enter",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

SUPERUSER_BREAK_GLASS_STATUS_ACTION: Action = register_action(
    Action(
        name="superuser.break_glass.status",
        required_permission=None,
        is_mutating=False,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

SUPERUSER_IP_ALLOWLIST_UPDATE_ACTION: Action = register_action(
    Action(
        name="superuser.ip_allowlist.update",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)


# =============================================================================
# Phase 2A.2 (spec 007) — dataset Actions (FR-008a, AD-1A behavior-preserving)
# =============================================================================
#
# All dataset resource CRUD/import/datetime-apply gate on the new
# MANAGE_DATASET_ADMIN permission (admin+owner only — AD-1B Option A).
# Read endpoints gate on VIEW_DATASET_LIST so members keep current access.
# Export gates on EXPORT (admin+owner per ROLE_PERMISSIONS).

DATASET_LIST_ACTION: Action = register_action(
    Action(
        name="dataset.list",
        required_permission=Permission.VIEW_DATASET_LIST,
        is_mutating=False,
    )
)

DATASET_GET_ACTION: Action = register_action(
    Action(
        name="dataset.get",
        required_permission=Permission.VIEW_DATASET_LIST,
        is_mutating=False,
    )
)

DATASET_CREATE_ACTION: Action = register_action(
    Action(
        name="dataset.create",
        required_permission=Permission.MANAGE_DATASET_ADMIN,
        is_mutating=True,
    )
)

DATASET_UPDATE_ACTION: Action = register_action(
    Action(
        name="dataset.update",
        required_permission=Permission.MANAGE_DATASET_ADMIN,
        is_mutating=True,
    )
)

DATASET_DELETE_ACTION: Action = register_action(
    Action(
        name="dataset.delete",
        required_permission=Permission.MANAGE_DATASET_ADMIN,
        is_mutating=True,
    )
)

DATASET_IMPORT_ACTION: Action = register_action(
    Action(
        name="dataset.import",
        required_permission=Permission.MANAGE_DATASET_ADMIN,
        is_mutating=True,
    )
)

DATASET_IMPORT_STATUS_ACTION: Action = register_action(
    Action(
        name="dataset.import_status",
        required_permission=Permission.VIEW_DATASET_LIST,
        is_mutating=False,
    )
)

DATASET_EXPORT_ACTION: Action = register_action(
    Action(
        name="dataset.export",
        required_permission=Permission.EXPORT,
        is_mutating=False,
    )
)

DATASET_STATISTICS_ACTION: Action = register_action(
    Action(
        name="dataset.statistics",
        required_permission=Permission.VIEW_DATASET_LIST,
        is_mutating=False,
    )
)

DATASET_DATETIME_CONFIG_ACTION: Action = register_action(
    Action(
        name="dataset.datetime_config.get",
        required_permission=Permission.VIEW_DATASET_LIST,
        is_mutating=False,
    )
)

# Auto-detect is a POST but it only inspects existing recordings and produces
# a candidate pattern (no DB write). Gate on MANAGE_DATASET_ADMIN (admin-only
# operation per current is_project_admin guard) but mark is_mutating=False so
# the archived-project gate / read-only audit treats it correctly.
DATASET_DATETIME_AUTODETECT_ACTION: Action = register_action(
    Action(
        name="dataset.datetime_config.auto_detect",
        required_permission=Permission.MANAGE_DATASET_ADMIN,
        is_mutating=False,
    )
)

DATASET_DATETIME_TEST_ACTION: Action = register_action(
    Action(
        name="dataset.datetime_config.test",
        required_permission=Permission.VIEW_DATASET_LIST,
        is_mutating=False,
    )
)

DATASET_DATETIME_APPLY_ACTION: Action = register_action(
    Action(
        name="dataset.datetime_config.apply",
        required_permission=Permission.MANAGE_DATASET_ADMIN,
        is_mutating=True,
    )
)


# =============================================================================
# Phase 2A.3 (spec 007) — clip Actions
# =============================================================================
#
# Clip CONTENT operations (create/update/delete/generate) gate on
# MANAGE_DATASET (members can mutate clips today via check_project_access).
# Read endpoints gate on VIEW_MEDIA; download on DOWNLOAD.

CLIP_LIST_ACTION: Action = register_action(
    Action(
        name="clip.list",
        required_permission=Permission.VIEW_MEDIA,
        is_mutating=False,
    )
)

CLIP_GET_ACTION: Action = register_action(
    Action(
        name="clip.get",
        required_permission=Permission.VIEW_MEDIA,
        is_mutating=False,
    )
)

CLIP_CREATE_ACTION: Action = register_action(
    Action(
        name="clip.create",
        required_permission=Permission.MANAGE_DATASET,
        is_mutating=True,
    )
)

CLIP_UPDATE_ACTION: Action = register_action(
    Action(
        name="clip.update",
        required_permission=Permission.MANAGE_DATASET,
        is_mutating=True,
    )
)

CLIP_DELETE_ACTION: Action = register_action(
    Action(
        name="clip.delete",
        required_permission=Permission.MANAGE_DATASET,
        is_mutating=True,
    )
)

CLIP_GENERATE_ACTION: Action = register_action(
    Action(
        name="clip.generate",
        required_permission=Permission.MANAGE_DATASET,
        is_mutating=True,
    )
)

CLIP_AUDIO_ACTION: Action = register_action(
    Action(
        name="clip.audio",
        required_permission=Permission.VIEW_MEDIA,
        is_mutating=False,
    )
)

CLIP_SPECTROGRAM_ACTION: Action = register_action(
    Action(
        name="clip.spectrogram",
        required_permission=Permission.VIEW_MEDIA,
        is_mutating=False,
    )
)

CLIP_DOWNLOAD_ACTION: Action = register_action(
    Action(
        name="clip.download",
        required_permission=Permission.DOWNLOAD,
        is_mutating=False,
    )
)


# =============================================================================
# Phase 2A.4 (spec 007) — annotation sets / segments / time-range annotations
# =============================================================================

ANNOTATION_SET_LIST_ACTION: Action = register_action(
    Action(
        name="annotation_set.list",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

ANNOTATION_SET_GET_ACTION: Action = register_action(
    Action(
        name="annotation_set.get",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

ANNOTATION_SET_CREATE_ACTION: Action = register_action(
    Action(
        name="annotation_set.create",
        required_permission=Permission.ANNOTATE,
        is_mutating=True,
    )
)

ANNOTATION_SET_UPDATE_ACTION: Action = register_action(
    Action(
        name="annotation_set.update",
        required_permission=Permission.ANNOTATE,
        is_mutating=True,
    )
)

ANNOTATION_SET_DELETE_ACTION: Action = register_action(
    Action(
        name="annotation_set.delete",
        required_permission=Permission.ANNOTATE,
        is_mutating=True,
    )
)

ANNOTATION_SET_PALETTE_UPDATE_ACTION: Action = register_action(
    Action(
        name="annotation_set.palette.update",
        required_permission=Permission.ANNOTATE,
        is_mutating=True,
    )
)

ANNOTATION_SEGMENT_LIST_ACTION: Action = register_action(
    Action(
        name="annotation_segment.list",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

ANNOTATION_SEGMENT_GET_ACTION: Action = register_action(
    Action(
        name="annotation_segment.get",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

ANNOTATION_SEGMENT_UPDATE_ACTION: Action = register_action(
    Action(
        name="annotation_segment.update",
        required_permission=Permission.ANNOTATE,
        is_mutating=True,
    )
)

ANNOTATION_SEGMENT_NOTE_CREATE_ACTION: Action = register_action(
    Action(
        name="annotation_segment.note.create",
        required_permission=Permission.COMMENT,
        is_mutating=True,
    )
)

TIME_RANGE_ANNOTATION_CREATE_ACTION: Action = register_action(
    Action(
        name="time_range_annotation.create",
        required_permission=Permission.ANNOTATE,
        is_mutating=True,
    )
)

TIME_RANGE_ANNOTATION_UPDATE_ACTION: Action = register_action(
    Action(
        name="time_range_annotation.update",
        required_permission=Permission.ANNOTATE,
        is_mutating=True,
    )
)

TIME_RANGE_ANNOTATION_DELETE_ACTION: Action = register_action(
    Action(
        name="time_range_annotation.delete",
        required_permission=Permission.ANNOTATE,
        is_mutating=True,
    )
)

TIME_RANGE_ANNOTATION_NOTE_CREATE_ACTION: Action = register_action(
    Action(
        name="time_range_annotation.note.create",
        required_permission=Permission.COMMENT,
        is_mutating=True,
    )
)


# =============================================================================
# Phase 2A.5 (spec 007) — confirmed_region / detection_run / xeno_canto /
# search / evaluation / admin (superuser) Actions
# =============================================================================
#
# taxon_sensitivity_override_* Actions are intentionally NOT registered: the
# corresponding endpoints do not yet exist in apps/api/echoroo/api/v1/taxa.py
# (only /taxa, /taxa/search, /taxa/gbif-search, /taxa/{taxon_id} are present).
# Per the AD-1A "verify before register" rule and the spec 007 Rev.5.1
# fallback plan, we skip these registrations until the override endpoints are
# wired in a later task.
# xeno_canto.search is intentionally NOT registered as an Action either —
# spec 007 Rev.3 重要-3 classifies it as `external_proxy` (handled via the
# endpoint allowlist) rather than a project-scope Action.

CONFIRMED_REGION_LIST_ACTION: Action = register_action(
    Action(
        name="confirmed_region.list",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

CONFIRMED_REGION_CREATE_ACTION: Action = register_action(
    Action(
        name="confirmed_region.create",
        required_permission=Permission.MANAGE_DATASET_ADMIN,
        is_mutating=True,
    )
)

CONFIRMED_REGION_DELETE_ACTION: Action = register_action(
    Action(
        name="confirmed_region.delete",
        required_permission=Permission.MANAGE_DATASET_ADMIN,
        is_mutating=True,
    )
)

DETECTION_RUN_LIST_ACTION: Action = register_action(
    Action(
        name="detection_run.list",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

DETECTION_RUN_GET_ACTION: Action = register_action(
    Action(
        name="detection_run.get",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

DETECTION_RUN_CREATE_ACTION: Action = register_action(
    Action(
        name="detection_run.create",
        required_permission=Permission.RUN_INFERENCE,
        is_mutating=True,
    )
)

DETECTION_RUN_UPDATE_ACTION: Action = register_action(
    Action(
        name="detection_run.update",
        required_permission=Permission.MANAGE_DATASET_ADMIN,
        is_mutating=True,
    )
)

DETECTION_RUN_RETRY_ACTION: Action = register_action(
    Action(
        name="detection_run.retry",
        required_permission=Permission.RUN_INFERENCE,
        is_mutating=True,
    )
)

DETECTION_RUN_CANCEL_ACTION: Action = register_action(
    Action(
        name="detection_run.cancel",
        required_permission=Permission.MANAGE_DATASET_ADMIN,
        is_mutating=True,
    )
)

# xeno_canto audio/sonogram proxies — read-only, gated on VIEW_MEDIA. The
# /search endpoint goes via the allowlist (external proxy).
XENO_CANTO_AUDIO_ACTION: Action = register_action(
    Action(
        name="xeno_canto.audio",
        required_permission=Permission.VIEW_MEDIA,
        is_mutating=False,
    )
)

XENO_CANTO_SONOGRAM_ACTION: Action = register_action(
    Action(
        name="xeno_canto.sonogram",
        required_permission=Permission.VIEW_MEDIA,
        is_mutating=False,
    )
)

# Search session lifecycle — SEARCH_WITHIN_PROJECT is already enforced via
# SearchGate; the Action registration aligns the catalog with the gate.
SEARCH_SESSION_LIST_ACTION: Action = register_action(
    Action(
        name="search.session.list",
        required_permission=Permission.SEARCH_WITHIN_PROJECT,
        is_mutating=False,
    )
)

SEARCH_SESSION_GET_ACTION: Action = register_action(
    Action(
        name="search.session.get",
        required_permission=Permission.SEARCH_WITHIN_PROJECT,
        is_mutating=False,
    )
)

SEARCH_SESSION_DELETE_ACTION: Action = register_action(
    Action(
        name="search.session.delete",
        required_permission=Permission.SEARCH_WITHIN_PROJECT,
        is_mutating=True,
    )
)

SEARCH_SESSION_UPDATE_ACTION: Action = register_action(
    Action(
        name="search.session.update",
        required_permission=Permission.SEARCH_WITHIN_PROJECT,
        is_mutating=True,
    )
)

SEARCH_SESSION_RERUN_ACTION: Action = register_action(
    Action(
        name="search.session.rerun",
        required_permission=Permission.SEARCH_WITHIN_PROJECT,
        is_mutating=True,
    )
)

SEARCH_SESSION_REFERENCE_AUDIO_ACTION: Action = register_action(
    Action(
        name="search.session.reference_audio",
        required_permission=Permission.VIEW_MEDIA,
        is_mutating=False,
    )
)

SEARCH_SESSION_EXPORT_RECORDINGS_ACTION: Action = register_action(
    Action(
        name="search.session.export_recordings",
        required_permission=Permission.EXPORT,
        is_mutating=False,
    )
)

SEARCH_SESSION_EXPORT_CSV_ACTION: Action = register_action(
    Action(
        name="search.session.export_csv",
        required_permission=Permission.EXPORT,
        is_mutating=False,
    )
)

SEARCH_SESSION_DISTRIBUTION_ACTION: Action = register_action(
    Action(
        name="search.session.distribution",
        required_permission=Permission.SEARCH_WITHIN_PROJECT,
        is_mutating=False,
    )
)

SEARCH_SESSION_TIME_DISTRIBUTION_ACTION: Action = register_action(
    Action(
        name="search.session.time_distribution",
        required_permission=Permission.SEARCH_WITHIN_PROJECT,
        is_mutating=False,
    )
)

SEARCH_SESSION_SAMPLE_ACTION: Action = register_action(
    Action(
        name="search.session.sample",
        required_permission=Permission.SEARCH_WITHIN_PROJECT,
        is_mutating=False,
    )
)

SEARCH_SIMILARITY_ACTION: Action = register_action(
    Action(
        name="search.similarity",
        required_permission=Permission.SEARCH_WITHIN_PROJECT,
        is_mutating=False,
    )
)

SEARCH_SIMILARITY_BY_AUDIO_ACTION: Action = register_action(
    Action(
        name="search.similarity_by_audio",
        required_permission=Permission.SEARCH_WITHIN_PROJECT,
        is_mutating=False,
    )
)

SEARCH_EMBEDDING_STATS_ACTION: Action = register_action(
    Action(
        name="search.embedding_stats",
        required_permission=Permission.SEARCH_WITHIN_PROJECT,
        is_mutating=False,
    )
)

SEARCH_BATCH_CREATE_ACTION: Action = register_action(
    Action(
        name="search.batch.create",
        required_permission=Permission.SEARCH_WITHIN_PROJECT,
        is_mutating=True,
    )
)

SEARCH_BATCH_JOB_GET_ACTION: Action = register_action(
    Action(
        name="search.batch.job.get",
        required_permission=Permission.SEARCH_WITHIN_PROJECT,
        is_mutating=False,
    )
)

# search annotations sub-router (search/annotations.py) — annotation-style
# mutation on search results.
SEARCH_ANNOTATION_ACTION: Action = register_action(
    Action(
        name="search.annotation",
        required_permission=Permission.ANNOTATE,
        is_mutating=True,
    )
)

# Evaluation — annotation_set_router + run_router (no project_id prefix on
# the path; the service layer resolves project scope from the annotation_set
# / run id). Reads via VIEW_DETECTION, create via RUN_INFERENCE,
# delete via MANAGE_DATASET_ADMIN.
EVALUATION_CREATE_ACTION: Action = register_action(
    Action(
        name="evaluation.create",
        required_permission=Permission.RUN_INFERENCE,
        is_mutating=True,
    )
)

EVALUATION_RUNS_BY_SET_ACTION: Action = register_action(
    Action(
        name="evaluation.runs_by_set",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

EVALUATION_RUN_LIST_ACTION: Action = register_action(
    Action(
        name="evaluation.run.list",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

EVALUATION_RUN_GET_ACTION: Action = register_action(
    Action(
        name="evaluation.run.get",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
)

EVALUATION_RUN_DELETE_ACTION: Action = register_action(
    Action(
        name="evaluation.run.delete",
        required_permission=Permission.MANAGE_DATASET_ADMIN,
        is_mutating=True,
    )
)


# =============================================================================
# Phase 2A.5 — admin (superuser) Actions (FR-072, FR-084, FR-111)
# =============================================================================
#
# Endpoints under /api/v1/admin/* are guarded by ``CurrentSuperuser``. They
# are platform-scope (no project_id required) and so use the same shape as
# the SUPERUSER_* actions above: required_permission=None,
# is_superuser_only=True, is_platform_scope=True. The Step -1 / Step 0a gate
# branches in :func:`is_allowed` deny non-superusers regardless.

ADMIN_USERS_LIST_ACTION: Action = register_action(
    Action(
        name="admin.users.list",
        required_permission=None,
        is_mutating=False,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

ADMIN_USERS_UPDATE_ACTION: Action = register_action(
    Action(
        name="admin.users.update",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

ADMIN_SETTINGS_GET_ACTION: Action = register_action(
    Action(
        name="admin.settings.get",
        required_permission=None,
        is_mutating=False,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

ADMIN_SETTINGS_UPDATE_ACTION: Action = register_action(
    Action(
        name="admin.settings.update",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

ADMIN_LICENSE_LIST_ACTION: Action = register_action(
    Action(
        name="admin.license.list",
        required_permission=None,
        is_mutating=False,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

ADMIN_LICENSE_CREATE_ACTION: Action = register_action(
    Action(
        name="admin.license.create",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

ADMIN_LICENSE_GET_ACTION: Action = register_action(
    Action(
        name="admin.license.get",
        required_permission=None,
        is_mutating=False,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

ADMIN_LICENSE_UPDATE_ACTION: Action = register_action(
    Action(
        name="admin.license.update",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

ADMIN_LICENSE_DELETE_ACTION: Action = register_action(
    Action(
        name="admin.license.delete",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

ADMIN_RECORDER_LIST_ACTION: Action = register_action(
    Action(
        name="admin.recorder.list",
        required_permission=None,
        is_mutating=False,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

ADMIN_RECORDER_CREATE_ACTION: Action = register_action(
    Action(
        name="admin.recorder.create",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

ADMIN_RECORDER_GET_ACTION: Action = register_action(
    Action(
        name="admin.recorder.get",
        required_permission=None,
        is_mutating=False,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

ADMIN_RECORDER_UPDATE_ACTION: Action = register_action(
    Action(
        name="admin.recorder.update",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)

ADMIN_RECORDER_DELETE_ACTION: Action = register_action(
    Action(
        name="admin.recorder.delete",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)


# =============================================================================
# spec/011 §FR-011-201 — Admin password reset (Phase 6 / US4 / T310)
# =============================================================================
#
# The system-superuser-only password reset endpoint
# (``POST /web-api/v1/admin/users/{user_id}/reset-password``) is gated
# both by ``gate_action(ADMIN_USER_RESET_PASSWORD_ACTION)`` (this entry)
# and by ``require_step_up_token(SCOPE_ADMIN_RECOVERY)`` (FR-011-206
# step-up enforcement). The action is platform-scope (no ``project_id``)
# and ``is_superuser_only=True`` so the Step -1 API-key veto + Step 0a
# platform branch in :func:`is_allowed` deny every non-superuser caller
# — including project admins (FR-011-201 explicitly forbids project
# admins from invoking the reset; only the system superuser may).
ADMIN_USER_RESET_PASSWORD_ACTION: Action = register_action(
    Action(
        name="admin.user.reset_password",
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
)


# =============================================================================
# spec/011 §FR-011-101 — Member-kind invitation issue (Phase 7 / US2 / T200)
# =============================================================================
#
# Gates ``POST /web-api/v1/projects/{project_id}/invitations`` for issuing a
# Member-kind invitation (FR-011-101). Project scope, mutating, gated by
# ``MANAGE_MEMBERS`` (Owner + Admin per the canonical matrix). The handler
# delegates to ``services.invitation_service.create_invitation`` and surfaces
# the resulting one-shot ``signed_token_envelope`` as ``invitation_url`` in
# the response body (FR-011-102).
PROJECT_MEMBER_INVITATION_ISSUE_ACTION: Action = register_action(
    Action(
        name="project.member.invitation.issue",
        required_permission=Permission.MANAGE_MEMBERS,
        is_mutating=True,
    )
)

# =============================================================================
# spec/011 §FR-011-115 / Step 8 — Member-kind invitation revoke
# =============================================================================
#
# Gates ``POST /web-api/v1/projects/{project_id}/invitations/{invitation_id}/
# revoke`` (the bulk + revoke surface promised by the contract YAML). Project
# scope, mutating, gated by ``MANAGE_MEMBERS`` (Owner + Admin per the canonical
# matrix). The revoke surface is a separate Action from
# :data:`PROJECT_MEMBER_INVITATION_ISSUE_ACTION` so audit consumers can
# distinguish issue from revoke in ``project_audit_log.action`` filters
# (FR-011-115).
PROJECT_MEMBER_INVITATION_REVOKE_ACTION: Action = register_action(
    Action(
        name="project.member.invitation.revoke",
        required_permission=Permission.MANAGE_MEMBERS,
        is_mutating=True,
    )
)


__all__ = [
    # Project
    "PROJECT_DELETE_ACTION",
    "PROJECT_GET_ACTION",
    "PROJECT_LICENSE_HISTORY_ACTION",
    "PROJECT_LICENSE_UPDATE_ACTION",
    "PROJECT_MEMBER_INVITE_ACTION",
    "PROJECT_MEMBER_LIST_ACTION",
    "PROJECT_MEMBER_REMOVE_ACTION",
    "PROJECT_MEMBER_UPDATE_ROLE_ACTION",
    "PROJECT_RESTRICTED_CONFIG_UPDATE_ACTION",
    "PROJECT_TRANSFER_OWNERSHIP_ACTION",
    "PROJECT_TRUSTED_INVITE_ACTION",
    "PROJECT_TRUSTED_LIST_ACTION",
    "PROJECT_TRUSTED_REVOKE_ACTION",
    "PROJECT_TRUSTED_UPDATE_ACTION",
    "PROJECT_UPDATE_ACTION",
    # Detection / Annotation / Tag / Upload / Custom Model / Recording
    "ANNOTATION_COMMENT_CREATE_ACTION",
    "ANNOTATION_COMMENT_LIST_ACTION",
    "ANNOTATION_VOTE_CREATE_ACTION",
    "ANNOTATION_VOTE_LIST_ACTION",
    "CUSTOM_MODEL_DELETE_ACTION",
    "CUSTOM_MODEL_GET_ACTION",
    "CUSTOM_MODEL_LIST_ACTION",
    "CUSTOM_MODEL_TRAIN_ACTION",
    "DETECTION_CHANGE_SPECIES_ACTION",
    "DETECTION_CONFIRM_ACTION",
    "DETECTION_CREATE_ACTION",
    "DETECTION_DELETE_ACTION",
    "DETECTION_EXPORT_CSV_ACTION",
    "DETECTION_EXPORT_ML_DATASET_ACTION",
    "DETECTION_GET_ACTION",
    "DETECTION_LIST_ACTION",
    "DETECTION_REJECT_ACTION",
    "RECORDING_DELETE_ACTION",
    "RECORDING_LIST_ACTION",
    "RECORDING_MEDIA_ACTION",
    "RECORDING_UPDATE_ACTION",
    "SITE_CREATE_ACTION",
    "SITE_DELETE_ACTION",
    "SITE_GET_ACTION",
    "SITE_LIST_ACTION",
    "SITE_UPDATE_ACTION",
    "TAG_CREATE_ACTION",
    "TAG_DELETE_ACTION",
    "TAG_UPDATE_ACTION",
    "UPLOAD_CREATE_ACTION",
    # Superuser admin (Phase 11 / T630)
    "PLATFORM_IUCN_FORCE_RESYNC_ACTION",
    "PROJECT_TAXON_OVERRIDE_APPROVE_ACTION",
    "PROJECT_TAXON_OVERRIDE_REJECT_ACTION",
    # Project lifecycle (Phase 12 / T702)
    "PROJECT_ARCHIVE_ACTION",
    "PROJECT_RESTORE_ACTION",
    # Superuser CRUD (Phase 15 Batch 5a)
    "SUPERUSER_ADD_ACTION",
    "SUPERUSER_APPROVAL_REQUEST_LIST_ACTION",
    "SUPERUSER_APPROVE_REQUEST_ACTION",
    "SUPERUSER_BREAK_GLASS_ENTER_ACTION",
    "SUPERUSER_BREAK_GLASS_STATUS_ACTION",
    "SUPERUSER_IP_ALLOWLIST_UPDATE_ACTION",
    "SUPERUSER_LIST_ACTION",
    "SUPERUSER_REJECT_REQUEST_ACTION",
    "SUPERUSER_REVOKE_ACTION",
    # Phase 2A.2 (spec 007) — dataset
    "DATASET_CREATE_ACTION",
    "DATASET_DATETIME_APPLY_ACTION",
    "DATASET_DATETIME_AUTODETECT_ACTION",
    "DATASET_DATETIME_CONFIG_ACTION",
    "DATASET_DATETIME_TEST_ACTION",
    "DATASET_DELETE_ACTION",
    "DATASET_EXPORT_ACTION",
    "DATASET_GET_ACTION",
    "DATASET_IMPORT_ACTION",
    "DATASET_IMPORT_STATUS_ACTION",
    "DATASET_LIST_ACTION",
    "DATASET_STATISTICS_ACTION",
    "DATASET_UPDATE_ACTION",
    # Phase 2A.3 (spec 007) — clip
    "CLIP_AUDIO_ACTION",
    "CLIP_CREATE_ACTION",
    "CLIP_DELETE_ACTION",
    "CLIP_DOWNLOAD_ACTION",
    "CLIP_GENERATE_ACTION",
    "CLIP_GET_ACTION",
    "CLIP_LIST_ACTION",
    "CLIP_SPECTROGRAM_ACTION",
    "CLIP_UPDATE_ACTION",
    # Phase 2A.4 (spec 007) — annotation sets / segments / time-range annotations
    "ANNOTATION_SEGMENT_GET_ACTION",
    "ANNOTATION_SEGMENT_LIST_ACTION",
    "ANNOTATION_SEGMENT_NOTE_CREATE_ACTION",
    "ANNOTATION_SEGMENT_UPDATE_ACTION",
    "ANNOTATION_SET_CREATE_ACTION",
    "ANNOTATION_SET_DELETE_ACTION",
    "ANNOTATION_SET_GET_ACTION",
    "ANNOTATION_SET_LIST_ACTION",
    "ANNOTATION_SET_PALETTE_UPDATE_ACTION",
    "ANNOTATION_SET_UPDATE_ACTION",
    "TIME_RANGE_ANNOTATION_CREATE_ACTION",
    "TIME_RANGE_ANNOTATION_DELETE_ACTION",
    "TIME_RANGE_ANNOTATION_NOTE_CREATE_ACTION",
    "TIME_RANGE_ANNOTATION_UPDATE_ACTION",
    # Phase 2A.5 (spec 007) — confirmed_region / detection_run
    "CONFIRMED_REGION_CREATE_ACTION",
    "CONFIRMED_REGION_DELETE_ACTION",
    "CONFIRMED_REGION_LIST_ACTION",
    "DETECTION_RUN_CANCEL_ACTION",
    "DETECTION_RUN_CREATE_ACTION",
    "DETECTION_RUN_GET_ACTION",
    "DETECTION_RUN_LIST_ACTION",
    "DETECTION_RUN_RETRY_ACTION",
    "DETECTION_RUN_UPDATE_ACTION",
    # Phase 2A.5 (spec 007) — xeno_canto (proxy reads only)
    "XENO_CANTO_AUDIO_ACTION",
    "XENO_CANTO_SONOGRAM_ACTION",
    # Phase 2A.5 (spec 007) — search / evaluation
    "EVALUATION_CREATE_ACTION",
    "EVALUATION_RUNS_BY_SET_ACTION",
    "EVALUATION_RUN_DELETE_ACTION",
    "EVALUATION_RUN_GET_ACTION",
    "EVALUATION_RUN_LIST_ACTION",
    "SEARCH_ANNOTATION_ACTION",
    "SEARCH_BATCH_CREATE_ACTION",
    "SEARCH_BATCH_JOB_GET_ACTION",
    "SEARCH_EMBEDDING_STATS_ACTION",
    "SEARCH_SESSION_DELETE_ACTION",
    "SEARCH_SESSION_DISTRIBUTION_ACTION",
    "SEARCH_SESSION_EXPORT_CSV_ACTION",
    "SEARCH_SESSION_EXPORT_RECORDINGS_ACTION",
    "SEARCH_SESSION_GET_ACTION",
    "SEARCH_SESSION_LIST_ACTION",
    "SEARCH_SESSION_REFERENCE_AUDIO_ACTION",
    "SEARCH_SESSION_RERUN_ACTION",
    "SEARCH_SESSION_SAMPLE_ACTION",
    "SEARCH_SESSION_TIME_DISTRIBUTION_ACTION",
    "SEARCH_SESSION_UPDATE_ACTION",
    "SEARCH_SIMILARITY_ACTION",
    "SEARCH_SIMILARITY_BY_AUDIO_ACTION",
    # Phase 2A.5 (spec 007) — admin (superuser, platform-scope)
    "ADMIN_LICENSE_CREATE_ACTION",
    "ADMIN_LICENSE_DELETE_ACTION",
    "ADMIN_LICENSE_GET_ACTION",
    "ADMIN_LICENSE_LIST_ACTION",
    "ADMIN_LICENSE_UPDATE_ACTION",
    "ADMIN_RECORDER_CREATE_ACTION",
    "ADMIN_RECORDER_DELETE_ACTION",
    "ADMIN_RECORDER_GET_ACTION",
    "ADMIN_RECORDER_LIST_ACTION",
    "ADMIN_RECORDER_UPDATE_ACTION",
    "ADMIN_SETTINGS_GET_ACTION",
    "ADMIN_SETTINGS_UPDATE_ACTION",
    "ADMIN_USERS_LIST_ACTION",
    "ADMIN_USERS_UPDATE_ACTION",
    # spec/011 §FR-011-201 — Admin password reset
    "ADMIN_USER_RESET_PASSWORD_ACTION",
    # spec/011 §FR-011-101 — Member-kind invitation issue
    "PROJECT_MEMBER_INVITATION_ISSUE_ACTION",
    # spec/011 §FR-011-115 / Step 8 — Member-kind invitation revoke
    "PROJECT_MEMBER_INVITATION_REVOKE_ACTION",
]
