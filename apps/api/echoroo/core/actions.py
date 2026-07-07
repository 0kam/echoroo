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

Implementation note (W3-5)
--------------------------
The catalog is expressed as a **declarative table** (``_ACTION_ROWS``): one row
per Action holding the module constant name, the canonical action name, the
required Permission and the three boolean flags. A small factory loop builds and
:func:`register_action`-registers each row, storing the result in ``_BUILT``.
The explicit ``FOO_ACTION: Action = _BUILT["FOO_ACTION"]`` re-binding lines that
follow are REQUIRED for mypy strict (so consumers keep importing the constants
by identity with a statically-known type) — they are not redundant.

Do NOT rename any action-name string or constant, and do NOT change any field
value: the action-name strings are referenced elsewhere (e.g.
``SUPERUSER_PROJECT_SCOPE_ALLOWLIST``, ``superuser_approval_service``, and audit
log values). ``tests/unit/core/test_actions_golden.py`` machine-proves that the
serialized registry is byte-for-byte identical to the reviewed golden fixture;
any diff there means a semantic change and must be reviewed explicitly.
"""
from __future__ import annotations

from typing import NamedTuple

from echoroo.core.permissions import Action, Permission, register_action


class _Row(NamedTuple):
    """One declarative Action definition.

    ``const`` is the module-level constant name that routers import by identity;
    ``name`` is the canonical (wire/audit) action-name string. The remaining
    fields mirror :class:`echoroo.core.permissions.Action`. Default-false flags
    and the default ``None`` permission are omitted from most rows.
    """

    const: str
    name: str
    required_permission: Permission | None = None
    is_mutating: bool = False
    is_superuser_only: bool = False
    is_platform_scope: bool = False


# =============================================================================
# Declarative Action table (single source of truth)
# =============================================================================
#
# Column order: const, name, required_permission, is_mutating,
#               is_superuser_only, is_platform_scope
#
# Load-bearing rationale comments are preserved next to the rows they explain.
_ACTION_ROWS: tuple[_Row, ...] = (
    # -------------------------------------------------------------------------
    # Project (web_v1/projects/_*)
    # -------------------------------------------------------------------------
    _Row("PROJECT_GET_ACTION", "project.get", Permission.VIEW_PROJECT_METADATA),
    _Row("PROJECT_UPDATE_ACTION", "project.update", Permission.EDIT_PROJECT, True),
    _Row("PROJECT_DELETE_ACTION", "project.delete", Permission.DELETE_PROJECT, True),
    _Row(
        "PROJECT_TRANSFER_OWNERSHIP_ACTION",
        "project.transfer_ownership",
        Permission.TRANSFER_OWNERSHIP,
        True,
    ),
    _Row(
        "PROJECT_RESTRICTED_CONFIG_UPDATE_ACTION",
        "project.restricted_config.update",
        Permission.EDIT_PROJECT,
        True,
    ),
    _Row(
        "PROJECT_LICENSE_UPDATE_ACTION",
        "project.license.update",
        Permission.MANAGE_LICENSE,
        True,
    ),
    _Row(
        "PROJECT_LICENSE_HISTORY_ACTION",
        "project.license.history",
        Permission.VIEW_PROJECT_METADATA,
    ),
    _Row(
        "PROJECT_MEMBER_LIST_ACTION",
        "project.member.list",
        Permission.MANAGE_MEMBERS,
    ),
    _Row(
        "PROJECT_MEMBER_INVITE_ACTION",
        "project.member.invite",
        Permission.MANAGE_MEMBERS,
        True,
    ),
    _Row(
        "PROJECT_MEMBER_REMOVE_ACTION",
        "project.member.remove",
        Permission.MANAGE_MEMBERS,
        True,
    ),
    _Row(
        "PROJECT_MEMBER_UPDATE_ROLE_ACTION",
        "project.member.update_role",
        Permission.MANAGE_MEMBERS,
        True,
    ),
    # -------------------------------------------------------------------------
    # Trusted overlay management (Phase 10 / T510, FR-014 / FR-046 / FR-050)
    # -------------------------------------------------------------------------
    # Phase 10 Batch 2 Round 2 fix (致命 1): Per ``contracts/trusted.yaml`` GET
    # list is Owner / Admin. The Canonical Matrix (spec L425) restricts
    # ``MANAGE_TRUSTED`` to Owner only because INVITE / PATCH / DELETE are
    # Owner-exclusive (FR-050). To let Admin enumerate while keeping mutation
    # endpoints Owner-only we gate the read with ``MANAGE_MEMBERS`` (Owner +
    # Admin per the matrix); the mutating actions below keep ``MANAGE_TRUSTED``
    # so an Admin cannot escalate.
    _Row(
        "PROJECT_TRUSTED_LIST_ACTION",
        "project.trusted.list",
        Permission.MANAGE_MEMBERS,
    ),
    _Row(
        "PROJECT_TRUSTED_INVITE_ACTION",
        "project.trusted.invite",
        Permission.MANAGE_TRUSTED,
        True,
    ),
    _Row(
        "PROJECT_TRUSTED_UPDATE_ACTION",
        "project.trusted.update",
        Permission.MANAGE_TRUSTED,
        True,
    ),
    _Row(
        "PROJECT_TRUSTED_REVOKE_ACTION",
        "project.trusted.revoke",
        Permission.MANAGE_TRUSTED,
        True,
    ),
    # -------------------------------------------------------------------------
    # Detection / Annotation / Tag / Upload / Custom Model / Recording
    # -------------------------------------------------------------------------
    _Row("DETECTION_LIST_ACTION", "detection.list", Permission.VIEW_DETECTION),
    _Row("DETECTION_GET_ACTION", "detection.get", Permission.VIEW_DETECTION),
    _Row("DETECTION_EXPORT_CSV_ACTION", "detection.export_csv", Permission.EXPORT),
    _Row(
        "DETECTION_EXPORT_ML_DATASET_ACTION",
        "detection.export_ml_dataset",
        Permission.EXPORT,
        True,
    ),
    _Row("DETECTION_CREATE_ACTION", "detection.create", Permission.ANNOTATE, True),
    _Row("DETECTION_CONFIRM_ACTION", "detection.confirm", Permission.ANNOTATE, True),
    _Row("DETECTION_REJECT_ACTION", "detection.reject", Permission.ANNOTATE, True),
    _Row(
        "DETECTION_CHANGE_SPECIES_ACTION",
        "detection.change_species",
        Permission.ANNOTATE,
        True,
    ),
    _Row("DETECTION_DELETE_ACTION", "detection.delete", Permission.EDIT_PROJECT, True),
    _Row(
        "ANNOTATION_VOTE_LIST_ACTION",
        "annotation_vote.list",
        Permission.VIEW_DETECTION,
    ),
    _Row(
        "ANNOTATION_VOTE_CREATE_ACTION",
        "annotation_vote.create",
        Permission.VOTE,
        True,
    ),
    _Row(
        "ANNOTATION_COMMENT_LIST_ACTION",
        "annotation_comment.list",
        Permission.VIEW_DETECTION,
    ),
    _Row(
        "ANNOTATION_COMMENT_CREATE_ACTION",
        "annotation_comment.create",
        Permission.COMMENT,
        True,
    ),
    _Row("TAG_CREATE_ACTION", "tag.create", Permission.CREATE_TAG, True),
    _Row("TAG_UPDATE_ACTION", "tag.update", Permission.EDIT_PROJECT, True),
    _Row("TAG_DELETE_ACTION", "tag.delete", Permission.EDIT_PROJECT, True),
    _Row("UPLOAD_CREATE_ACTION", "upload.create", Permission.UPLOAD, True),
    _Row(
        "CUSTOM_MODEL_TRAIN_ACTION",
        "custom_model.train",
        Permission.TRAIN_MODEL,
        True,
    ),
    _Row("CUSTOM_MODEL_LIST_ACTION", "custom_model.list", Permission.VIEW_DETECTION),
    _Row("CUSTOM_MODEL_GET_ACTION", "custom_model.get", Permission.VIEW_DETECTION),
    _Row(
        "CUSTOM_MODEL_DELETE_ACTION",
        "custom_model.delete",
        Permission.EDIT_PROJECT,
        True,
    ),
    _Row("RECORDING_LIST_ACTION", "recording.list", Permission.VIEW_DETECTION),
    _Row("RECORDING_MEDIA_ACTION", "recording.media", Permission.VIEW_MEDIA),
    _Row("RECORDING_UPDATE_ACTION", "recording.update", Permission.MANAGE_DATASET, True),
    _Row("RECORDING_DELETE_ACTION", "recording.delete", Permission.MANAGE_DATASET, True),
    _Row("SITE_LIST_ACTION", "site.list", Permission.VIEW_DETECTION),
    _Row("SITE_GET_ACTION", "site.get", Permission.VIEW_DETECTION),
    _Row("SITE_CREATE_ACTION", "site.create", Permission.MANAGE_SITE, True),
    _Row("SITE_UPDATE_ACTION", "site.update", Permission.MANAGE_SITE, True),
    _Row("SITE_DELETE_ACTION", "site.delete", Permission.MANAGE_SITE, True),
    # -------------------------------------------------------------------------
    # Phase 11 / T630 — superuser admin endpoints (FR-034 / FR-036 / FR-111)
    # -------------------------------------------------------------------------
    #
    # The two looser-override mutations are *project-scope* actions (a project_id
    # is required to load the override row and write a project_audit_log entry),
    # but the Stage-1 gate also short-circuits them through
    # ``SUPERUSER_PROJECT_SCOPE_ALLOWLIST`` (FR-008b) so a superuser without an
    # explicit Permission cell still passes. ``required_permission`` is therefore
    # set to a sentinel value the matrix never grants outside the allowlist
    # branch — non-superusers always fail closed.
    #
    # For approve_looser specifically: outside the allowlist short-circuit
    # (FR-008b), the approval is reserved to superusers; ``EDIT_PROJECT`` is the
    # closest matrix cell (Owner-only) so a non-superuser caller still fails the
    # Permission check.
    _Row(
        "PROJECT_TAXON_OVERRIDE_APPROVE_ACTION",
        "project.taxon_override.approve_looser",
        Permission.EDIT_PROJECT,
        True,
    ),
    _Row(
        "PROJECT_TAXON_OVERRIDE_REJECT_ACTION",
        "project.taxon_override.reject_looser",
        Permission.EDIT_PROJECT,
        True,
    ),
    # Phase 12 / T702 — superuser-only project lifecycle (FR-061 / FR-062). Both
    # actions are project-scope (a project_id is required to lock the row and
    # write a project_audit_log entry) but they MUST NEVER be reachable via the
    # normal Matrix path — an Owner who happens to satisfy the nominal
    # ``EDIT_PROJECT`` permission must NOT be able to archive their own project.
    # Phase 12 R1 致命 C1 fix: we mark both actions ``is_superuser_only=True``
    # so :func:`echoroo.core.permissions.is_allowed` Step 0c hard-fails any
    # non-superuser caller before the Matrix check is consulted.
    # ``SUPERUSER_PROJECT_SCOPE_ALLOWLIST`` (FR-008b) provides the positive
    # branch for superusers via Step 0b. The ``required_permission`` slot below
    # is a sentinel that would only be evaluated if both Step 0b and Step 0c were
    # bypassed — neither happens in practice.
    _Row(
        "PROJECT_ARCHIVE_ACTION",
        "project.archive",
        Permission.EDIT_PROJECT,
        True,
        True,
    ),
    _Row(
        "PROJECT_RESTORE_ACTION",
        "project.restore",
        Permission.EDIT_PROJECT,
        True,
        True,
    ),
    # IUCN force-resync is platform-scope: there is no project_id parameter and
    # the Celery task rewrites the global ``taxon_sensitivity`` table. We mark
    # the action ``is_platform_scope=True`` so :func:`is_allowed` routes it
    # through the Step-0a superuser-only branch.
    _Row(
        "PLATFORM_IUCN_FORCE_RESYNC_ACTION",
        "platform.iucn.force_resync",
        None,
        True,
        True,
        True,
    ),
    # Taxon-catalog maintenance triggers are platform-scope (no project_id) and
    # rewrite global taxonomy tables (``taxa`` / ``taxon_vernacular_names``). They
    # mirror the IUCN force-resync action above: ``is_platform_scope=True`` routes
    # them through the Step-0a superuser-only branch in :func:`is_allowed`, and the
    # universal Step -1 api_key veto denies any API-key principal.
    _Row(
        "PLATFORM_TAXON_SEED_BIRDNET_ACTION",
        "platform.taxon.seed_birdnet",
        None,
        True,
        True,
        True,
    ),
    _Row(
        "PLATFORM_TAXON_SYNC_VERNACULAR_ACTION",
        "platform.taxon.sync_vernacular",
        None,
        True,
        True,
        True,
    ),
    # Upload-session recovery is platform-scope (no project_id parameter): the
    # superuser inspects and force-fails stuck upload sessions across every
    # project so a wedged import can be unblocked (the user then re-uploads).
    # ``is_platform_scope=True`` routes it through the Step-0a superuser-only
    # branch, and ``is_mutating=True`` because the fail action rewrites session
    # state. The Step -1 universal api_key veto denies any API-key principal.
    _Row(
        "PLATFORM_UPLOAD_RECOVER_ACTION",
        "platform.upload.recover",
        None,
        True,
        True,
        True,
    ),
    # -------------------------------------------------------------------------
    # Phase 15 Batch 5a — Superuser CRUD admin endpoints (FR-111 / FR-072 / FR-084)
    # -------------------------------------------------------------------------
    #
    # These platform-scope actions back the ``/web-api/v1/admin/superusers/*``
    # endpoints. All carry ``is_superuser_only=True`` so the Step -1 universal
    # api_key veto in :func:`echoroo.core.permissions.is_allowed` denies any
    # API-key principal regardless of its scopes (FR-084 PR-007). Cookie / JWT
    # session callers fall through to the Step 0a branch which permits only
    # authenticated superusers.
    _Row("SUPERUSER_LIST_ACTION", "superuser.list", None, False, True, True),
    _Row("SUPERUSER_ADD_ACTION", "superuser.add", None, True, True, True),
    _Row("SUPERUSER_REVOKE_ACTION", "superuser.revoke", None, True, True, True),
    _Row(
        "SUPERUSER_APPROVAL_REQUEST_LIST_ACTION",
        "superuser.approval.list",
        None,
        False,
        True,
        True,
    ),
    _Row(
        "SUPERUSER_APPROVE_REQUEST_ACTION",
        "superuser.approval.approve",
        None,
        True,
        True,
        True,
    ),
    _Row(
        "SUPERUSER_REJECT_REQUEST_ACTION",
        "superuser.approval.reject",
        None,
        True,
        True,
        True,
    ),
    _Row(
        "SUPERUSER_BREAK_GLASS_ENTER_ACTION",
        "superuser.break_glass.enter",
        None,
        True,
        True,
        True,
    ),
    _Row(
        "SUPERUSER_BREAK_GLASS_STATUS_ACTION",
        "superuser.break_glass.status",
        None,
        False,
        True,
        True,
    ),
    _Row(
        "SUPERUSER_IP_ALLOWLIST_UPDATE_ACTION",
        "superuser.ip_allowlist.update",
        None,
        True,
        True,
        True,
    ),
    # -------------------------------------------------------------------------
    # Phase 2A.2 (spec 007) — dataset Actions (FR-008a, AD-1A behavior-preserving)
    # -------------------------------------------------------------------------
    #
    # All dataset resource CRUD/import/datetime-apply gate on the new
    # MANAGE_DATASET_ADMIN permission (admin+owner only — AD-1B Option A).
    # Read endpoints gate on VIEW_DATASET_LIST so members keep current access.
    # Export gates on EXPORT (admin+owner per ROLE_PERMISSIONS).
    _Row("DATASET_LIST_ACTION", "dataset.list", Permission.VIEW_DATASET_LIST),
    _Row("DATASET_GET_ACTION", "dataset.get", Permission.VIEW_DATASET_LIST),
    _Row(
        "DATASET_CREATE_ACTION",
        "dataset.create",
        Permission.MANAGE_DATASET_ADMIN,
        True,
    ),
    _Row(
        "DATASET_UPDATE_ACTION",
        "dataset.update",
        Permission.MANAGE_DATASET_ADMIN,
        True,
    ),
    _Row(
        "DATASET_DELETE_ACTION",
        "dataset.delete",
        Permission.MANAGE_DATASET_ADMIN,
        True,
    ),
    _Row(
        "DATASET_IMPORT_ACTION",
        "dataset.import",
        Permission.MANAGE_DATASET_ADMIN,
        True,
    ),
    _Row(
        "DATASET_IMPORT_STATUS_ACTION",
        "dataset.import_status",
        Permission.VIEW_DATASET_LIST,
    ),
    _Row("DATASET_EXPORT_ACTION", "dataset.export", Permission.EXPORT),
    _Row(
        "DATASET_STATISTICS_ACTION",
        "dataset.statistics",
        Permission.VIEW_DATASET_LIST,
    ),
    _Row(
        "DATASET_DATETIME_CONFIG_ACTION",
        "dataset.datetime_config.get",
        Permission.VIEW_DATASET_LIST,
    ),
    # Auto-detect is a POST but it only inspects existing recordings and produces
    # a candidate pattern (no DB write). Gate on MANAGE_DATASET_ADMIN (admin-only
    # operation per current is_project_admin guard) but mark is_mutating=False so
    # the archived-project gate / read-only audit treats it correctly.
    _Row(
        "DATASET_DATETIME_AUTODETECT_ACTION",
        "dataset.datetime_config.auto_detect",
        Permission.MANAGE_DATASET_ADMIN,
    ),
    _Row(
        "DATASET_DATETIME_TEST_ACTION",
        "dataset.datetime_config.test",
        Permission.VIEW_DATASET_LIST,
    ),
    _Row(
        "DATASET_DATETIME_APPLY_ACTION",
        "dataset.datetime_config.apply",
        Permission.MANAGE_DATASET_ADMIN,
        True,
    ),
    # -------------------------------------------------------------------------
    # Phase 2A.3 (spec 007) — clip Actions
    # -------------------------------------------------------------------------
    #
    # Clip CONTENT operations (create/update/delete/generate) gate on
    # MANAGE_DATASET (members can mutate clips today via check_project_access).
    # Read endpoints gate on VIEW_MEDIA; download on DOWNLOAD.
    _Row("CLIP_LIST_ACTION", "clip.list", Permission.VIEW_MEDIA),
    _Row("CLIP_GET_ACTION", "clip.get", Permission.VIEW_MEDIA),
    _Row("CLIP_CREATE_ACTION", "clip.create", Permission.MANAGE_DATASET, True),
    _Row("CLIP_UPDATE_ACTION", "clip.update", Permission.MANAGE_DATASET, True),
    _Row("CLIP_DELETE_ACTION", "clip.delete", Permission.MANAGE_DATASET, True),
    _Row("CLIP_GENERATE_ACTION", "clip.generate", Permission.MANAGE_DATASET, True),
    _Row("CLIP_AUDIO_ACTION", "clip.audio", Permission.VIEW_MEDIA),
    _Row("CLIP_SPECTROGRAM_ACTION", "clip.spectrogram", Permission.VIEW_MEDIA),
    _Row("CLIP_DOWNLOAD_ACTION", "clip.download", Permission.DOWNLOAD),
    # -------------------------------------------------------------------------
    # Phase 2A.4 (spec 007) — annotation sets / segments / time-range annotations
    # -------------------------------------------------------------------------
    _Row(
        "ANNOTATION_SET_LIST_ACTION",
        "annotation_set.list",
        Permission.VIEW_DETECTION,
    ),
    _Row("ANNOTATION_SET_GET_ACTION", "annotation_set.get", Permission.VIEW_DETECTION),
    _Row(
        "ANNOTATION_SET_CREATE_ACTION",
        "annotation_set.create",
        Permission.ANNOTATE,
        True,
    ),
    _Row(
        "ANNOTATION_SET_UPDATE_ACTION",
        "annotation_set.update",
        Permission.ANNOTATE,
        True,
    ),
    _Row(
        "ANNOTATION_SET_DELETE_ACTION",
        "annotation_set.delete",
        Permission.ANNOTATE,
        True,
    ),
    _Row(
        "ANNOTATION_SET_PALETTE_UPDATE_ACTION",
        "annotation_set.palette.update",
        Permission.ANNOTATE,
        True,
    ),
    _Row(
        "ANNOTATION_SEGMENT_LIST_ACTION",
        "annotation_segment.list",
        Permission.VIEW_DETECTION,
    ),
    _Row(
        "ANNOTATION_SEGMENT_GET_ACTION",
        "annotation_segment.get",
        Permission.VIEW_DETECTION,
    ),
    _Row(
        "ANNOTATION_SEGMENT_UPDATE_ACTION",
        "annotation_segment.update",
        Permission.ANNOTATE,
        True,
    ),
    _Row(
        "ANNOTATION_SEGMENT_NOTE_CREATE_ACTION",
        "annotation_segment.note.create",
        Permission.COMMENT,
        True,
    ),
    _Row(
        "TIME_RANGE_ANNOTATION_CREATE_ACTION",
        "time_range_annotation.create",
        Permission.ANNOTATE,
        True,
    ),
    _Row(
        "TIME_RANGE_ANNOTATION_UPDATE_ACTION",
        "time_range_annotation.update",
        Permission.ANNOTATE,
        True,
    ),
    _Row(
        "TIME_RANGE_ANNOTATION_DELETE_ACTION",
        "time_range_annotation.delete",
        Permission.ANNOTATE,
        True,
    ),
    _Row(
        "TIME_RANGE_ANNOTATION_NOTE_CREATE_ACTION",
        "time_range_annotation.note.create",
        Permission.COMMENT,
        True,
    ),
    # -------------------------------------------------------------------------
    # Phase 2A.5 (spec 007) — confirmed_region / detection_run / xeno_canto /
    # search / evaluation / admin (superuser) Actions
    # -------------------------------------------------------------------------
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
    _Row(
        "CONFIRMED_REGION_LIST_ACTION",
        "confirmed_region.list",
        Permission.VIEW_DETECTION,
    ),
    _Row(
        "CONFIRMED_REGION_CREATE_ACTION",
        "confirmed_region.create",
        Permission.MANAGE_DATASET_ADMIN,
        True,
    ),
    _Row(
        "CONFIRMED_REGION_DELETE_ACTION",
        "confirmed_region.delete",
        Permission.MANAGE_DATASET_ADMIN,
        True,
    ),
    _Row("DETECTION_RUN_LIST_ACTION", "detection_run.list", Permission.VIEW_DETECTION),
    _Row("DETECTION_RUN_GET_ACTION", "detection_run.get", Permission.VIEW_DETECTION),
    _Row(
        "DETECTION_RUN_CREATE_ACTION",
        "detection_run.create",
        Permission.RUN_INFERENCE,
        True,
    ),
    _Row(
        "DETECTION_RUN_UPDATE_ACTION",
        "detection_run.update",
        Permission.MANAGE_DATASET_ADMIN,
        True,
    ),
    _Row(
        "DETECTION_RUN_RETRY_ACTION",
        "detection_run.retry",
        Permission.RUN_INFERENCE,
        True,
    ),
    _Row(
        "DETECTION_RUN_CANCEL_ACTION",
        "detection_run.cancel",
        Permission.MANAGE_DATASET_ADMIN,
        True,
    ),
    # xeno_canto audio/sonogram proxies — read-only, gated on VIEW_MEDIA. The
    # /search endpoint goes via the allowlist (external proxy).
    _Row("XENO_CANTO_AUDIO_ACTION", "xeno_canto.audio", Permission.VIEW_MEDIA),
    _Row("XENO_CANTO_SONOGRAM_ACTION", "xeno_canto.sonogram", Permission.VIEW_MEDIA),
    # Search session lifecycle — SEARCH_WITHIN_PROJECT is already enforced via
    # SearchGate; the Action registration aligns the catalog with the gate.
    _Row(
        "SEARCH_SESSION_LIST_ACTION",
        "search.session.list",
        Permission.SEARCH_WITHIN_PROJECT,
    ),
    _Row(
        "SEARCH_SESSION_GET_ACTION",
        "search.session.get",
        Permission.SEARCH_WITHIN_PROJECT,
    ),
    _Row(
        "SEARCH_SESSION_DELETE_ACTION",
        "search.session.delete",
        Permission.SEARCH_WITHIN_PROJECT,
        True,
    ),
    _Row(
        "SEARCH_SESSION_UPDATE_ACTION",
        "search.session.update",
        Permission.SEARCH_WITHIN_PROJECT,
        True,
    ),
    _Row(
        "SEARCH_SESSION_RERUN_ACTION",
        "search.session.rerun",
        Permission.SEARCH_WITHIN_PROJECT,
        True,
    ),
    _Row(
        "SEARCH_SESSION_REFERENCE_AUDIO_ACTION",
        "search.session.reference_audio",
        Permission.VIEW_MEDIA,
    ),
    _Row(
        "SEARCH_SESSION_EXPORT_RECORDINGS_ACTION",
        "search.session.export_recordings",
        Permission.EXPORT,
    ),
    _Row(
        "SEARCH_SESSION_EXPORT_CSV_ACTION",
        "search.session.export_csv",
        Permission.EXPORT,
    ),
    _Row(
        "SEARCH_SESSION_DISTRIBUTION_ACTION",
        "search.session.distribution",
        Permission.SEARCH_WITHIN_PROJECT,
    ),
    _Row(
        "SEARCH_SESSION_TIME_DISTRIBUTION_ACTION",
        "search.session.time_distribution",
        Permission.SEARCH_WITHIN_PROJECT,
    ),
    _Row(
        "SEARCH_SESSION_SAMPLE_ACTION",
        "search.session.sample",
        Permission.SEARCH_WITHIN_PROJECT,
    ),
    _Row(
        "SEARCH_SIMILARITY_ACTION",
        "search.similarity",
        Permission.SEARCH_WITHIN_PROJECT,
    ),
    _Row(
        "SEARCH_SIMILARITY_BY_AUDIO_ACTION",
        "search.similarity_by_audio",
        Permission.SEARCH_WITHIN_PROJECT,
    ),
    _Row(
        "SEARCH_EMBEDDING_STATS_ACTION",
        "search.embedding_stats",
        Permission.SEARCH_WITHIN_PROJECT,
    ),
    _Row(
        "SEARCH_BATCH_CREATE_ACTION",
        "search.batch.create",
        Permission.SEARCH_WITHIN_PROJECT,
        True,
    ),
    _Row(
        "SEARCH_BATCH_JOB_GET_ACTION",
        "search.batch.job.get",
        Permission.SEARCH_WITHIN_PROJECT,
    ),
    # search annotations sub-router (search/annotations.py) — annotation-style
    # mutation on search results.
    _Row("SEARCH_ANNOTATION_ACTION", "search.annotation", Permission.ANNOTATE, True),
    # Evaluation — annotation_set_router + run_router (no project_id prefix on
    # the path; the service layer resolves project scope from the annotation_set
    # / run id). Reads via VIEW_DETECTION, create via RUN_INFERENCE, delete via
    # MANAGE_DATASET_ADMIN.
    _Row("EVALUATION_CREATE_ACTION", "evaluation.create", Permission.RUN_INFERENCE, True),
    _Row(
        "EVALUATION_RUNS_BY_SET_ACTION",
        "evaluation.runs_by_set",
        Permission.VIEW_DETECTION,
    ),
    _Row("EVALUATION_RUN_LIST_ACTION", "evaluation.run.list", Permission.VIEW_DETECTION),
    _Row("EVALUATION_RUN_GET_ACTION", "evaluation.run.get", Permission.VIEW_DETECTION),
    _Row(
        "EVALUATION_RUN_DELETE_ACTION",
        "evaluation.run.delete",
        Permission.MANAGE_DATASET_ADMIN,
        True,
    ),
    # -------------------------------------------------------------------------
    # Phase 2A.5 — admin (superuser) Actions (FR-072, FR-084, FR-111)
    # -------------------------------------------------------------------------
    #
    # Endpoints under /api/v1/admin/* are guarded by ``CurrentSuperuser``. They
    # are platform-scope (no project_id required) and so use the same shape as
    # the SUPERUSER_* actions above: required_permission=None,
    # is_superuser_only=True, is_platform_scope=True. The Step -1 / Step 0a gate
    # branches in :func:`is_allowed` deny non-superusers regardless.
    _Row("ADMIN_USERS_LIST_ACTION", "admin.users.list", None, False, True, True),
    _Row("ADMIN_USERS_UPDATE_ACTION", "admin.users.update", None, True, True, True),
    _Row("ADMIN_SETTINGS_GET_ACTION", "admin.settings.get", None, False, True, True),
    _Row("ADMIN_SETTINGS_UPDATE_ACTION", "admin.settings.update", None, True, True, True),
    _Row("ADMIN_LICENSE_LIST_ACTION", "admin.license.list", None, False, True, True),
    _Row("ADMIN_LICENSE_CREATE_ACTION", "admin.license.create", None, True, True, True),
    _Row("ADMIN_LICENSE_GET_ACTION", "admin.license.get", None, False, True, True),
    _Row("ADMIN_LICENSE_UPDATE_ACTION", "admin.license.update", None, True, True, True),
    _Row("ADMIN_LICENSE_DELETE_ACTION", "admin.license.delete", None, True, True, True),
    _Row("ADMIN_RECORDER_LIST_ACTION", "admin.recorder.list", None, False, True, True),
    _Row("ADMIN_RECORDER_CREATE_ACTION", "admin.recorder.create", None, True, True, True),
    _Row("ADMIN_RECORDER_GET_ACTION", "admin.recorder.get", None, False, True, True),
    _Row("ADMIN_RECORDER_UPDATE_ACTION", "admin.recorder.update", None, True, True, True),
    _Row("ADMIN_RECORDER_DELETE_ACTION", "admin.recorder.delete", None, True, True, True),
    # -------------------------------------------------------------------------
    # spec/011 §FR-011-201 — Admin password reset (Phase 6 / US4 / T310)
    # -------------------------------------------------------------------------
    #
    # The system-superuser-only password reset endpoint
    # (``POST /web-api/v1/admin/users/{user_id}/reset-password``) is gated both
    # by ``gate_action(ADMIN_USER_RESET_PASSWORD_ACTION)`` (this entry) and by
    # ``require_step_up_token(SCOPE_ADMIN_RECOVERY)`` (FR-011-206 step-up
    # enforcement). The action is platform-scope (no ``project_id``) and
    # ``is_superuser_only=True`` so the Step -1 API-key veto + Step 0a platform
    # branch in :func:`is_allowed` deny every non-superuser caller — including
    # project admins (FR-011-201 explicitly forbids project admins from invoking
    # the reset; only the system superuser may).
    _Row(
        "ADMIN_USER_RESET_PASSWORD_ACTION",
        "admin.user.reset_password",
        None,
        True,
        True,
        True,
    ),
    # -------------------------------------------------------------------------
    # spec/011 §FR-011-101 — Member-kind invitation issue (Phase 7 / US2 / T200)
    # -------------------------------------------------------------------------
    #
    # Gates ``POST /web-api/v1/projects/{project_id}/invitations`` for issuing a
    # Member-kind invitation (FR-011-101). Project scope, mutating, gated by
    # ``MANAGE_MEMBERS`` (Owner + Admin per the canonical matrix). The handler
    # delegates to ``services.invitation_service.create_invitation`` and surfaces
    # the resulting one-shot ``signed_token_envelope`` as ``invitation_url`` in
    # the response body (FR-011-102).
    _Row(
        "PROJECT_MEMBER_INVITATION_ISSUE_ACTION",
        "project.member.invitation.issue",
        Permission.MANAGE_MEMBERS,
        True,
    ),
    # -------------------------------------------------------------------------
    # spec/011 §FR-011-115 / Step 8 — Member-kind invitation revoke
    # -------------------------------------------------------------------------
    #
    # Gates ``POST /web-api/v1/projects/{project_id}/invitations/{invitation_id}/
    # revoke`` (the bulk + revoke surface promised by the contract YAML). Project
    # scope, mutating, gated by ``MANAGE_MEMBERS`` (Owner + Admin per the canonical
    # matrix). The revoke surface is a separate Action from
    # :data:`PROJECT_MEMBER_INVITATION_ISSUE_ACTION` so audit consumers can
    # distinguish issue from revoke in ``project_audit_log.action`` filters
    # (FR-011-115).
    _Row(
        "PROJECT_MEMBER_INVITATION_REVOKE_ACTION",
        "project.member.invitation.revoke",
        Permission.MANAGE_MEMBERS,
        True,
    ),
)


# =============================================================================
# Factory loop — build + register every Action from the declarative table
# =============================================================================

_BUILT: dict[str, Action] = {}
for _row in _ACTION_ROWS:
    if _row.const in _BUILT:
        raise ValueError(f"Duplicate Action constant in table: {_row.const!r}")
    _BUILT[_row.const] = register_action(
        Action(
            name=_row.name,
            required_permission=_row.required_permission,
            is_mutating=_row.is_mutating,
            is_superuser_only=_row.is_superuser_only,
            is_platform_scope=_row.is_platform_scope,
        )
    )


# =============================================================================
# Explicit typed re-binding (REQUIRED for mypy strict — see module docstring)
# =============================================================================

# Project
PROJECT_GET_ACTION: Action = _BUILT["PROJECT_GET_ACTION"]
PROJECT_UPDATE_ACTION: Action = _BUILT["PROJECT_UPDATE_ACTION"]
PROJECT_DELETE_ACTION: Action = _BUILT["PROJECT_DELETE_ACTION"]
PROJECT_TRANSFER_OWNERSHIP_ACTION: Action = _BUILT["PROJECT_TRANSFER_OWNERSHIP_ACTION"]
PROJECT_RESTRICTED_CONFIG_UPDATE_ACTION: Action = _BUILT[
    "PROJECT_RESTRICTED_CONFIG_UPDATE_ACTION"
]
PROJECT_LICENSE_UPDATE_ACTION: Action = _BUILT["PROJECT_LICENSE_UPDATE_ACTION"]
PROJECT_LICENSE_HISTORY_ACTION: Action = _BUILT["PROJECT_LICENSE_HISTORY_ACTION"]
PROJECT_MEMBER_LIST_ACTION: Action = _BUILT["PROJECT_MEMBER_LIST_ACTION"]
PROJECT_MEMBER_INVITE_ACTION: Action = _BUILT["PROJECT_MEMBER_INVITE_ACTION"]
PROJECT_MEMBER_REMOVE_ACTION: Action = _BUILT["PROJECT_MEMBER_REMOVE_ACTION"]
PROJECT_MEMBER_UPDATE_ROLE_ACTION: Action = _BUILT["PROJECT_MEMBER_UPDATE_ROLE_ACTION"]

# Trusted overlay management
PROJECT_TRUSTED_LIST_ACTION: Action = _BUILT["PROJECT_TRUSTED_LIST_ACTION"]
PROJECT_TRUSTED_INVITE_ACTION: Action = _BUILT["PROJECT_TRUSTED_INVITE_ACTION"]
PROJECT_TRUSTED_UPDATE_ACTION: Action = _BUILT["PROJECT_TRUSTED_UPDATE_ACTION"]
PROJECT_TRUSTED_REVOKE_ACTION: Action = _BUILT["PROJECT_TRUSTED_REVOKE_ACTION"]

# Detection / Annotation / Tag / Upload / Custom Model / Recording
DETECTION_LIST_ACTION: Action = _BUILT["DETECTION_LIST_ACTION"]
DETECTION_GET_ACTION: Action = _BUILT["DETECTION_GET_ACTION"]
DETECTION_EXPORT_CSV_ACTION: Action = _BUILT["DETECTION_EXPORT_CSV_ACTION"]
DETECTION_EXPORT_ML_DATASET_ACTION: Action = _BUILT["DETECTION_EXPORT_ML_DATASET_ACTION"]
DETECTION_CREATE_ACTION: Action = _BUILT["DETECTION_CREATE_ACTION"]
DETECTION_CONFIRM_ACTION: Action = _BUILT["DETECTION_CONFIRM_ACTION"]
DETECTION_REJECT_ACTION: Action = _BUILT["DETECTION_REJECT_ACTION"]
DETECTION_CHANGE_SPECIES_ACTION: Action = _BUILT["DETECTION_CHANGE_SPECIES_ACTION"]
DETECTION_DELETE_ACTION: Action = _BUILT["DETECTION_DELETE_ACTION"]
ANNOTATION_VOTE_LIST_ACTION: Action = _BUILT["ANNOTATION_VOTE_LIST_ACTION"]
ANNOTATION_VOTE_CREATE_ACTION: Action = _BUILT["ANNOTATION_VOTE_CREATE_ACTION"]
ANNOTATION_COMMENT_LIST_ACTION: Action = _BUILT["ANNOTATION_COMMENT_LIST_ACTION"]
ANNOTATION_COMMENT_CREATE_ACTION: Action = _BUILT["ANNOTATION_COMMENT_CREATE_ACTION"]
TAG_CREATE_ACTION: Action = _BUILT["TAG_CREATE_ACTION"]
TAG_UPDATE_ACTION: Action = _BUILT["TAG_UPDATE_ACTION"]
TAG_DELETE_ACTION: Action = _BUILT["TAG_DELETE_ACTION"]
UPLOAD_CREATE_ACTION: Action = _BUILT["UPLOAD_CREATE_ACTION"]
CUSTOM_MODEL_TRAIN_ACTION: Action = _BUILT["CUSTOM_MODEL_TRAIN_ACTION"]
CUSTOM_MODEL_LIST_ACTION: Action = _BUILT["CUSTOM_MODEL_LIST_ACTION"]
CUSTOM_MODEL_GET_ACTION: Action = _BUILT["CUSTOM_MODEL_GET_ACTION"]
CUSTOM_MODEL_DELETE_ACTION: Action = _BUILT["CUSTOM_MODEL_DELETE_ACTION"]
RECORDING_LIST_ACTION: Action = _BUILT["RECORDING_LIST_ACTION"]
RECORDING_MEDIA_ACTION: Action = _BUILT["RECORDING_MEDIA_ACTION"]
RECORDING_UPDATE_ACTION: Action = _BUILT["RECORDING_UPDATE_ACTION"]
RECORDING_DELETE_ACTION: Action = _BUILT["RECORDING_DELETE_ACTION"]
SITE_LIST_ACTION: Action = _BUILT["SITE_LIST_ACTION"]
SITE_GET_ACTION: Action = _BUILT["SITE_GET_ACTION"]
SITE_CREATE_ACTION: Action = _BUILT["SITE_CREATE_ACTION"]
SITE_UPDATE_ACTION: Action = _BUILT["SITE_UPDATE_ACTION"]
SITE_DELETE_ACTION: Action = _BUILT["SITE_DELETE_ACTION"]

# Superuser admin (Phase 11 / T630) + project lifecycle (Phase 12 / T702)
PROJECT_TAXON_OVERRIDE_APPROVE_ACTION: Action = _BUILT[
    "PROJECT_TAXON_OVERRIDE_APPROVE_ACTION"
]
PROJECT_TAXON_OVERRIDE_REJECT_ACTION: Action = _BUILT[
    "PROJECT_TAXON_OVERRIDE_REJECT_ACTION"
]
PROJECT_ARCHIVE_ACTION: Action = _BUILT["PROJECT_ARCHIVE_ACTION"]
PROJECT_RESTORE_ACTION: Action = _BUILT["PROJECT_RESTORE_ACTION"]
PLATFORM_IUCN_FORCE_RESYNC_ACTION: Action = _BUILT["PLATFORM_IUCN_FORCE_RESYNC_ACTION"]
PLATFORM_TAXON_SEED_BIRDNET_ACTION: Action = _BUILT["PLATFORM_TAXON_SEED_BIRDNET_ACTION"]
PLATFORM_TAXON_SYNC_VERNACULAR_ACTION: Action = _BUILT[
    "PLATFORM_TAXON_SYNC_VERNACULAR_ACTION"
]
PLATFORM_UPLOAD_RECOVER_ACTION: Action = _BUILT["PLATFORM_UPLOAD_RECOVER_ACTION"]

# Superuser CRUD (Phase 15 Batch 5a)
SUPERUSER_LIST_ACTION: Action = _BUILT["SUPERUSER_LIST_ACTION"]
SUPERUSER_ADD_ACTION: Action = _BUILT["SUPERUSER_ADD_ACTION"]
SUPERUSER_REVOKE_ACTION: Action = _BUILT["SUPERUSER_REVOKE_ACTION"]
SUPERUSER_APPROVAL_REQUEST_LIST_ACTION: Action = _BUILT[
    "SUPERUSER_APPROVAL_REQUEST_LIST_ACTION"
]
SUPERUSER_APPROVE_REQUEST_ACTION: Action = _BUILT["SUPERUSER_APPROVE_REQUEST_ACTION"]
SUPERUSER_REJECT_REQUEST_ACTION: Action = _BUILT["SUPERUSER_REJECT_REQUEST_ACTION"]
SUPERUSER_BREAK_GLASS_ENTER_ACTION: Action = _BUILT["SUPERUSER_BREAK_GLASS_ENTER_ACTION"]
SUPERUSER_BREAK_GLASS_STATUS_ACTION: Action = _BUILT[
    "SUPERUSER_BREAK_GLASS_STATUS_ACTION"
]
SUPERUSER_IP_ALLOWLIST_UPDATE_ACTION: Action = _BUILT[
    "SUPERUSER_IP_ALLOWLIST_UPDATE_ACTION"
]

# Phase 2A.2 (spec 007) — dataset
DATASET_LIST_ACTION: Action = _BUILT["DATASET_LIST_ACTION"]
DATASET_GET_ACTION: Action = _BUILT["DATASET_GET_ACTION"]
DATASET_CREATE_ACTION: Action = _BUILT["DATASET_CREATE_ACTION"]
DATASET_UPDATE_ACTION: Action = _BUILT["DATASET_UPDATE_ACTION"]
DATASET_DELETE_ACTION: Action = _BUILT["DATASET_DELETE_ACTION"]
DATASET_IMPORT_ACTION: Action = _BUILT["DATASET_IMPORT_ACTION"]
DATASET_IMPORT_STATUS_ACTION: Action = _BUILT["DATASET_IMPORT_STATUS_ACTION"]
DATASET_EXPORT_ACTION: Action = _BUILT["DATASET_EXPORT_ACTION"]
DATASET_STATISTICS_ACTION: Action = _BUILT["DATASET_STATISTICS_ACTION"]
DATASET_DATETIME_CONFIG_ACTION: Action = _BUILT["DATASET_DATETIME_CONFIG_ACTION"]
DATASET_DATETIME_AUTODETECT_ACTION: Action = _BUILT["DATASET_DATETIME_AUTODETECT_ACTION"]
DATASET_DATETIME_TEST_ACTION: Action = _BUILT["DATASET_DATETIME_TEST_ACTION"]
DATASET_DATETIME_APPLY_ACTION: Action = _BUILT["DATASET_DATETIME_APPLY_ACTION"]

# Phase 2A.3 (spec 007) — clip
CLIP_LIST_ACTION: Action = _BUILT["CLIP_LIST_ACTION"]
CLIP_GET_ACTION: Action = _BUILT["CLIP_GET_ACTION"]
CLIP_CREATE_ACTION: Action = _BUILT["CLIP_CREATE_ACTION"]
CLIP_UPDATE_ACTION: Action = _BUILT["CLIP_UPDATE_ACTION"]
CLIP_DELETE_ACTION: Action = _BUILT["CLIP_DELETE_ACTION"]
CLIP_GENERATE_ACTION: Action = _BUILT["CLIP_GENERATE_ACTION"]
CLIP_AUDIO_ACTION: Action = _BUILT["CLIP_AUDIO_ACTION"]
CLIP_SPECTROGRAM_ACTION: Action = _BUILT["CLIP_SPECTROGRAM_ACTION"]
CLIP_DOWNLOAD_ACTION: Action = _BUILT["CLIP_DOWNLOAD_ACTION"]

# Phase 2A.4 (spec 007) — annotation sets / segments / time-range annotations
ANNOTATION_SET_LIST_ACTION: Action = _BUILT["ANNOTATION_SET_LIST_ACTION"]
ANNOTATION_SET_GET_ACTION: Action = _BUILT["ANNOTATION_SET_GET_ACTION"]
ANNOTATION_SET_CREATE_ACTION: Action = _BUILT["ANNOTATION_SET_CREATE_ACTION"]
ANNOTATION_SET_UPDATE_ACTION: Action = _BUILT["ANNOTATION_SET_UPDATE_ACTION"]
ANNOTATION_SET_DELETE_ACTION: Action = _BUILT["ANNOTATION_SET_DELETE_ACTION"]
ANNOTATION_SET_PALETTE_UPDATE_ACTION: Action = _BUILT[
    "ANNOTATION_SET_PALETTE_UPDATE_ACTION"
]
ANNOTATION_SEGMENT_LIST_ACTION: Action = _BUILT["ANNOTATION_SEGMENT_LIST_ACTION"]
ANNOTATION_SEGMENT_GET_ACTION: Action = _BUILT["ANNOTATION_SEGMENT_GET_ACTION"]
ANNOTATION_SEGMENT_UPDATE_ACTION: Action = _BUILT["ANNOTATION_SEGMENT_UPDATE_ACTION"]
ANNOTATION_SEGMENT_NOTE_CREATE_ACTION: Action = _BUILT[
    "ANNOTATION_SEGMENT_NOTE_CREATE_ACTION"
]
TIME_RANGE_ANNOTATION_CREATE_ACTION: Action = _BUILT[
    "TIME_RANGE_ANNOTATION_CREATE_ACTION"
]
TIME_RANGE_ANNOTATION_UPDATE_ACTION: Action = _BUILT[
    "TIME_RANGE_ANNOTATION_UPDATE_ACTION"
]
TIME_RANGE_ANNOTATION_DELETE_ACTION: Action = _BUILT[
    "TIME_RANGE_ANNOTATION_DELETE_ACTION"
]
TIME_RANGE_ANNOTATION_NOTE_CREATE_ACTION: Action = _BUILT[
    "TIME_RANGE_ANNOTATION_NOTE_CREATE_ACTION"
]

# Phase 2A.5 (spec 007) — confirmed_region / detection_run
CONFIRMED_REGION_LIST_ACTION: Action = _BUILT["CONFIRMED_REGION_LIST_ACTION"]
CONFIRMED_REGION_CREATE_ACTION: Action = _BUILT["CONFIRMED_REGION_CREATE_ACTION"]
CONFIRMED_REGION_DELETE_ACTION: Action = _BUILT["CONFIRMED_REGION_DELETE_ACTION"]
DETECTION_RUN_LIST_ACTION: Action = _BUILT["DETECTION_RUN_LIST_ACTION"]
DETECTION_RUN_GET_ACTION: Action = _BUILT["DETECTION_RUN_GET_ACTION"]
DETECTION_RUN_CREATE_ACTION: Action = _BUILT["DETECTION_RUN_CREATE_ACTION"]
DETECTION_RUN_UPDATE_ACTION: Action = _BUILT["DETECTION_RUN_UPDATE_ACTION"]
DETECTION_RUN_RETRY_ACTION: Action = _BUILT["DETECTION_RUN_RETRY_ACTION"]
DETECTION_RUN_CANCEL_ACTION: Action = _BUILT["DETECTION_RUN_CANCEL_ACTION"]

# Phase 2A.5 (spec 007) — xeno_canto (proxy reads only)
XENO_CANTO_AUDIO_ACTION: Action = _BUILT["XENO_CANTO_AUDIO_ACTION"]
XENO_CANTO_SONOGRAM_ACTION: Action = _BUILT["XENO_CANTO_SONOGRAM_ACTION"]

# Phase 2A.5 (spec 007) — search
SEARCH_SESSION_LIST_ACTION: Action = _BUILT["SEARCH_SESSION_LIST_ACTION"]
SEARCH_SESSION_GET_ACTION: Action = _BUILT["SEARCH_SESSION_GET_ACTION"]
SEARCH_SESSION_DELETE_ACTION: Action = _BUILT["SEARCH_SESSION_DELETE_ACTION"]
SEARCH_SESSION_UPDATE_ACTION: Action = _BUILT["SEARCH_SESSION_UPDATE_ACTION"]
SEARCH_SESSION_RERUN_ACTION: Action = _BUILT["SEARCH_SESSION_RERUN_ACTION"]
SEARCH_SESSION_REFERENCE_AUDIO_ACTION: Action = _BUILT[
    "SEARCH_SESSION_REFERENCE_AUDIO_ACTION"
]
SEARCH_SESSION_EXPORT_RECORDINGS_ACTION: Action = _BUILT[
    "SEARCH_SESSION_EXPORT_RECORDINGS_ACTION"
]
SEARCH_SESSION_EXPORT_CSV_ACTION: Action = _BUILT["SEARCH_SESSION_EXPORT_CSV_ACTION"]
SEARCH_SESSION_DISTRIBUTION_ACTION: Action = _BUILT["SEARCH_SESSION_DISTRIBUTION_ACTION"]
SEARCH_SESSION_TIME_DISTRIBUTION_ACTION: Action = _BUILT[
    "SEARCH_SESSION_TIME_DISTRIBUTION_ACTION"
]
SEARCH_SESSION_SAMPLE_ACTION: Action = _BUILT["SEARCH_SESSION_SAMPLE_ACTION"]
SEARCH_SIMILARITY_ACTION: Action = _BUILT["SEARCH_SIMILARITY_ACTION"]
SEARCH_SIMILARITY_BY_AUDIO_ACTION: Action = _BUILT["SEARCH_SIMILARITY_BY_AUDIO_ACTION"]
SEARCH_EMBEDDING_STATS_ACTION: Action = _BUILT["SEARCH_EMBEDDING_STATS_ACTION"]
SEARCH_BATCH_CREATE_ACTION: Action = _BUILT["SEARCH_BATCH_CREATE_ACTION"]
SEARCH_BATCH_JOB_GET_ACTION: Action = _BUILT["SEARCH_BATCH_JOB_GET_ACTION"]
SEARCH_ANNOTATION_ACTION: Action = _BUILT["SEARCH_ANNOTATION_ACTION"]

# Phase 2A.5 (spec 007) — evaluation
EVALUATION_CREATE_ACTION: Action = _BUILT["EVALUATION_CREATE_ACTION"]
EVALUATION_RUNS_BY_SET_ACTION: Action = _BUILT["EVALUATION_RUNS_BY_SET_ACTION"]
EVALUATION_RUN_LIST_ACTION: Action = _BUILT["EVALUATION_RUN_LIST_ACTION"]
EVALUATION_RUN_GET_ACTION: Action = _BUILT["EVALUATION_RUN_GET_ACTION"]
EVALUATION_RUN_DELETE_ACTION: Action = _BUILT["EVALUATION_RUN_DELETE_ACTION"]

# Phase 2A.5 (spec 007) — admin (superuser, platform-scope)
ADMIN_USERS_LIST_ACTION: Action = _BUILT["ADMIN_USERS_LIST_ACTION"]
ADMIN_USERS_UPDATE_ACTION: Action = _BUILT["ADMIN_USERS_UPDATE_ACTION"]
ADMIN_SETTINGS_GET_ACTION: Action = _BUILT["ADMIN_SETTINGS_GET_ACTION"]
ADMIN_SETTINGS_UPDATE_ACTION: Action = _BUILT["ADMIN_SETTINGS_UPDATE_ACTION"]
ADMIN_LICENSE_LIST_ACTION: Action = _BUILT["ADMIN_LICENSE_LIST_ACTION"]
ADMIN_LICENSE_CREATE_ACTION: Action = _BUILT["ADMIN_LICENSE_CREATE_ACTION"]
ADMIN_LICENSE_GET_ACTION: Action = _BUILT["ADMIN_LICENSE_GET_ACTION"]
ADMIN_LICENSE_UPDATE_ACTION: Action = _BUILT["ADMIN_LICENSE_UPDATE_ACTION"]
ADMIN_LICENSE_DELETE_ACTION: Action = _BUILT["ADMIN_LICENSE_DELETE_ACTION"]
ADMIN_RECORDER_LIST_ACTION: Action = _BUILT["ADMIN_RECORDER_LIST_ACTION"]
ADMIN_RECORDER_CREATE_ACTION: Action = _BUILT["ADMIN_RECORDER_CREATE_ACTION"]
ADMIN_RECORDER_GET_ACTION: Action = _BUILT["ADMIN_RECORDER_GET_ACTION"]
ADMIN_RECORDER_UPDATE_ACTION: Action = _BUILT["ADMIN_RECORDER_UPDATE_ACTION"]
ADMIN_RECORDER_DELETE_ACTION: Action = _BUILT["ADMIN_RECORDER_DELETE_ACTION"]

# spec/011 §FR-011-201 — Admin password reset
ADMIN_USER_RESET_PASSWORD_ACTION: Action = _BUILT["ADMIN_USER_RESET_PASSWORD_ACTION"]

# spec/011 §FR-011-101 — Member-kind invitation issue
PROJECT_MEMBER_INVITATION_ISSUE_ACTION: Action = _BUILT[
    "PROJECT_MEMBER_INVITATION_ISSUE_ACTION"
]

# spec/011 §FR-011-115 / Step 8 — Member-kind invitation revoke
PROJECT_MEMBER_INVITATION_REVOKE_ACTION: Action = _BUILT[
    "PROJECT_MEMBER_INVITATION_REVOKE_ACTION"
]


# ``__all__`` is derived from the declarative table so it can never drift from
# the set of registered constants. ``test_actions_golden.py`` asserts the
# three-way equality between ``__all__``, the table constants, and ``_BUILT``.
__all__ = [_row.const for _row in _ACTION_ROWS]
