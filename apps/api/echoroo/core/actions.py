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
]
