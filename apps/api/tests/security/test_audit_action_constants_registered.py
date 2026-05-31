"""spec/011 §NFR-011-005 / T024 — audit-action constant registration guard.

NFR-011-005 introduces eleven new ``platform_audit_log`` /
``project_audit_log`` ``action`` strings. The codebase has no single
enum module, so each constant is declared service-private at the call
site of the service that emits it (T020). This guard pins three
invariants so a future maintainer cannot silently regress the
contract:

1. **Canonical value** — each declared constant resolves to the exact
   string spec/011 ``data-model.md §Audit Events`` specifies. A typo
   (e.g. ``platform.user.email_change`` vs ``email_changed``) would
   split the banner/activity consumers from the emitter.

2. **Uniqueness** — no two new constants collide, and none collides
   with a pre-existing audit-action string already in use elsewhere in
   the codebase (``auth.password_changed``, ``two_factor_reset.*``,
   ``superuser.*`` etc.). Collision would make audit queries ambiguous.

3. **A-13 PII detector allowlist** — every constant is a plain
   ``verb.noun.verb`` ASCII string that the Phase 17 A-13 operator
   free-form PII detector (:func:`echoroo.core.audit.contains_pii`)
   accepts. The audit-action strings are service-private constants, NOT
   operator input, so the relevant "registration" at this layer is the
   negative assertion that the constant value does not itself embed a
   PII pattern (defence against a maintainer naming a constant
   ``platform.user.email.update_for_jane@example.com``). This is the
   same allowlist semantics the sibling guard
   ``test_pre_transfer_action_summary_destructive_allowlist.py`` applies
   to the invitation/ownership constants.

The constants are imported from their owning service modules so a
rename in those modules breaks this test loudly (the import fails),
keeping the registry honest.
"""

from __future__ import annotations

from echoroo.core.audit import contains_pii
from echoroo.services.admin_password_reset import (
    AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_BY_SUPERUSER,
    AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_SELF,
)
from echoroo.services.api_key_lifecycle import (
    AUDIT_ACTION_PLATFORM_API_KEY_REVOKE,
    AUDIT_ACTION_PLATFORM_API_KEY_SCOPE_DEGRADE,
)
from echoroo.services.audit_service import DESTRUCTIVE_ACTIONS
from echoroo.services.auth import AUDIT_ACTION_AUTH_LOGIN_NEW_DEVICE
from echoroo.services.invitation_service import (
    AUDIT_ACTION_MEMBER_INVITE_ACCEPTED,
    AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP,
    AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
    AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED,
)
from echoroo.services.trusted_device_service import (
    AUDIT_ACTION_AUTH_TRUSTED_DEVICE_REVOKE_ALL,
)
from echoroo.services.two_factor_reset_service import (
    AUDIT_ACTION_PLATFORM_USER_TWO_FACTOR_RESET_BY_SUPERUSER,
)
from echoroo.services.user import AUDIT_ACTION_PLATFORM_USER_EMAIL_CHANGED
from echoroo.services.user_banner import BANNER_ELIGIBLE_ACTIONS

# ---------------------------------------------------------------------------
# The eleven spec/011 NFR-011-005 audit-action constants, keyed by the
# canonical string value spec/011 data-model.md §Audit Events specifies.
# The mapping is the contract: constant-name -> expected literal value.
# ---------------------------------------------------------------------------

_NFR_011_005_CONSTANTS: dict[str, str] = {
    # invitation_service.py
    "AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP": (
        "project.member.invite_accepted_signup"
    ),
    "AUDIT_ACTION_MEMBER_INVITE_ACCEPTED": "project.member.invite_accepted",
    "AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED": "project.trusted_user.invite_accepted",
    "AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER": (
        "project.ownership.bootstrap_transfer"
    ),
    # admin_password_reset.py
    "AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_BY_SUPERUSER": (
        "platform.user.password_reset_by_superuser"
    ),
    "AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_SELF": (
        "platform.user.password_reset_self"
    ),
    # auth.py
    "AUDIT_ACTION_AUTH_LOGIN_NEW_DEVICE": "auth.login.new_device",
    # api_key_lifecycle.py
    "AUDIT_ACTION_PLATFORM_API_KEY_REVOKE": "platform.api_key.revoke",
    # user.py
    "AUDIT_ACTION_PLATFORM_USER_EMAIL_CHANGED": "platform.user.email_changed",
    # two_factor_reset_service.py
    "AUDIT_ACTION_PLATFORM_USER_TWO_FACTOR_RESET_BY_SUPERUSER": (
        "platform.user.two_factor_reset_by_superuser"
    ),
    # trusted_device_service.py
    "AUDIT_ACTION_AUTH_TRUSTED_DEVICE_REVOKE_ALL": "auth.trusted_device.revoke_all",
}

#: The actual imported constant objects, name -> value. Imported (rather
#: than re-typed) so a rename in the owning module surfaces here as an
#: ImportError, not a silent skip.
_IMPORTED_CONSTANTS: dict[str, str] = {
    "AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP": (
        AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP
    ),
    "AUDIT_ACTION_MEMBER_INVITE_ACCEPTED": AUDIT_ACTION_MEMBER_INVITE_ACCEPTED,
    "AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED": AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED,
    "AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER": (
        AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER
    ),
    "AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_BY_SUPERUSER": (
        AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_BY_SUPERUSER
    ),
    "AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_SELF": (
        AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_SELF
    ),
    "AUDIT_ACTION_AUTH_LOGIN_NEW_DEVICE": AUDIT_ACTION_AUTH_LOGIN_NEW_DEVICE,
    "AUDIT_ACTION_PLATFORM_API_KEY_REVOKE": AUDIT_ACTION_PLATFORM_API_KEY_REVOKE,
    "AUDIT_ACTION_PLATFORM_USER_EMAIL_CHANGED": (
        AUDIT_ACTION_PLATFORM_USER_EMAIL_CHANGED
    ),
    "AUDIT_ACTION_PLATFORM_USER_TWO_FACTOR_RESET_BY_SUPERUSER": (
        AUDIT_ACTION_PLATFORM_USER_TWO_FACTOR_RESET_BY_SUPERUSER
    ),
    "AUDIT_ACTION_AUTH_TRUSTED_DEVICE_REVOKE_ALL": (
        AUDIT_ACTION_AUTH_TRUSTED_DEVICE_REVOKE_ALL
    ),
}

#: Pre-existing audit-action strings declared elsewhere in the codebase.
#: A new spec/011 constant MUST NOT collide with any of these. This is a
#: representative (not exhaustive) snapshot harvested from the existing
#: service modules; collision against any of them would make an audit
#: query ambiguous between two distinct event semantics.
_PRE_EXISTING_AUDIT_ACTIONS: frozenset[str] = frozenset(
    {
        "api_key.auto_revoke_ip_violation",
        "api_key.ip_violation",
        "auth.password_changed",
        "auth.two_factor_enforcement_blocked",
        "project.invitation.revoke",
        "project.invitation.create",
        "project.invitation.accept",
        "project.invitation.decline",
        "project.taxon_override.approve_looser",
        "project.taxon_override.create_stricter",
        "project.taxon_override.reject_looser",
        "project.taxon_override.request_looser",
        "project.transfer_ownership",
        "project.trusted_user.auto_expire",
        "project.trusted_user.expiry_notice",
        "superuser.add.applied",
        "superuser.add.direct",
        "superuser.add.requested",
        "superuser.approval.approved",
        "superuser.approval.rejected",
        "superuser.break_glass.entered",
        "superuser.count_changed",
        "superuser.revoke.applied",
        "superuser.revoke.requested",
        "superuser.webauthn.registered",
        "two_factor.reset_completed",
        "two_factor_reset.applied",
        "two_factor_reset.cancelled",
        "two_factor_reset.confirmation_token_issued",
        "two_factor_reset.confirmation_token_redeemed",
        "two_factor_reset.dispatched",
        "two_factor_reset.dispatching_reclaimed",
        "two_factor_reset.email_notification_failed",
        "two_factor_reset.expired",
        "two_factor_reset.failed",
        "two_factor_reset.requested",
        "two_factor_reset.token_verified",
        "user.self_delete",
    }
)


# ---------------------------------------------------------------------------
# 1. Canonical value — each constant resolves to the spec string.
# ---------------------------------------------------------------------------


def test_each_constant_has_canonical_spec_value() -> None:
    """Every NFR-011-005 constant equals its data-model.md canonical string."""
    for name, expected in _NFR_011_005_CONSTANTS.items():
        actual = _IMPORTED_CONSTANTS[name]
        assert actual == expected, (
            f"audit-action constant {name} = {actual!r} but spec/011 "
            f"data-model.md requires {expected!r} — emitter and "
            "banner/activity consumers will drift"
        )


def test_all_eleven_constants_are_declared() -> None:
    """Exactly the eleven NFR-011-005 strings are declared (no drift)."""
    declared_values = set(_IMPORTED_CONSTANTS.values())
    expected_values = set(_NFR_011_005_CONSTANTS.values())
    assert declared_values == expected_values
    assert len(expected_values) == 11, (
        "NFR-011-005 enumerates exactly 11 new audit-action strings; "
        f"this guard tracks {len(expected_values)}"
    )


# ---------------------------------------------------------------------------
# 2. Uniqueness — no internal collision, no collision with existing strings.
# ---------------------------------------------------------------------------


def test_constants_are_internally_unique() -> None:
    """No two NFR-011-005 constants resolve to the same string."""
    values = list(_IMPORTED_CONSTANTS.values())
    assert len(values) == len(set(values)), (
        f"duplicate audit-action string among NFR-011-005 constants: {values}"
    )


def test_constants_do_not_collide_with_existing_actions() -> None:
    """No NFR-011-005 string shadows a pre-existing audit-action string."""
    collisions = set(_IMPORTED_CONSTANTS.values()) & _PRE_EXISTING_AUDIT_ACTIONS
    assert not collisions, (
        f"NFR-011-005 audit-action strings collide with existing actions: "
        f"{sorted(collisions)}"
    )


def test_scope_degrade_companion_constant_is_unique() -> None:
    """The companion ``platform.api_key.scope_degrade`` (US7 T613) is unique.

    Declared alongside ``platform.api_key.revoke`` in
    :mod:`echoroo.services.api_key_lifecycle` so US7 can emit it without
    a fresh constant decl. Guard it for uniqueness here so a future
    edit cannot accidentally alias it onto ``revoke`` or any existing
    string.
    """
    assert (
        AUDIT_ACTION_PLATFORM_API_KEY_SCOPE_DEGRADE == "platform.api_key.scope_degrade"
    )
    assert AUDIT_ACTION_PLATFORM_API_KEY_SCOPE_DEGRADE not in _PRE_EXISTING_AUDIT_ACTIONS
    assert (
        AUDIT_ACTION_PLATFORM_API_KEY_SCOPE_DEGRADE
        not in set(_IMPORTED_CONSTANTS.values())
    )


# ---------------------------------------------------------------------------
# 3. A-13 PII detector allowlist — no constant trips the PII regex.
# ---------------------------------------------------------------------------


def test_no_constant_trips_pii_detector() -> None:
    """Every NFR-011-005 string is accepted by the A-13 PII detector.

    The audit-action strings are service-private constants, not operator
    input, so "registered with the A-13 detector" means the value is a
    clean ``verb.noun.verb`` token the detector does not flag. A future
    maintainer embedding an email / phone / token in a constant value
    would otherwise persist PII into the ``action`` column plaintext.
    """
    for name, value in _IMPORTED_CONSTANTS.items():
        assert not contains_pii(value), (
            f"audit-action constant {name} = {value!r} matches a PII "
            "pattern — rename the constant before merging"
        )
    # The companion scope_degrade constant rides the same gate.
    assert not contains_pii(AUDIT_ACTION_PLATFORM_API_KEY_SCOPE_DEGRADE)


# ---------------------------------------------------------------------------
# 4. DESTRUCTIVE_ACTIONS membership coherence (T023).
# ---------------------------------------------------------------------------


def test_destructive_actions_membership_is_coherent() -> None:
    """The DESTRUCTIVE_ACTIONS registry is consistent with NFR-011-005.

    Per spec/011 research R6, the password-reset actions are the only
    NFR-011-005 strings classified destructive (their per-row
    ``target_id`` must survive the SU-bootstrap pre-transfer summary
    projection). The invite/ownership/login/email/2fa-reset/api-key
    strings are NON-destructive and MUST NOT be members, or the summary
    projection would leak their target ids (FR-011-307).
    """
    expected_destructive = {
        "platform.user.password_reset_by_superuser",
        "platform.user.password_reset_self",
    }
    for value in expected_destructive:
        assert value in DESTRUCTIVE_ACTIONS, (
            f"{value!r} must be classified destructive (R6) but is "
            "absent from DESTRUCTIVE_ACTIONS"
        )

    non_destructive = set(_IMPORTED_CONSTANTS.values()) - expected_destructive
    leaked = non_destructive & DESTRUCTIVE_ACTIONS
    assert not leaked, (
        f"non-destructive NFR-011-005 actions wrongly classified "
        f"destructive (R6 target_id leak risk): {sorted(leaked)}"
    )


def test_banner_eligible_actions_cover_nfr_011_005_targets() -> None:
    """The banner-eligible registry covers the NFR-011-005 banner targets.

    spec/011 FR-011-008 enumerates the in-app banner targets; every
    NFR-011-005 string except the two password-reset destructive rows'
    *self/by-superuser* split nuance is banner-eligible. Concretely the
    six platform/auth user-facing events plus the four invite/ownership
    accept events MUST be members so the affected user sees them in
    ``GET /me/banners`` / the activity timeline.
    """
    required = {
        AUDIT_ACTION_AUTH_LOGIN_NEW_DEVICE,
        AUDIT_ACTION_PLATFORM_USER_EMAIL_CHANGED,
        AUDIT_ACTION_PLATFORM_USER_TWO_FACTOR_RESET_BY_SUPERUSER,
        AUDIT_ACTION_PLATFORM_API_KEY_REVOKE,
        AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_BY_SUPERUSER,
        AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_SELF,
        AUDIT_ACTION_MEMBER_INVITE_ACCEPTED,
        AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP,
        AUDIT_ACTION_TRUSTED_INVITE_ACCEPTED,
        AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
        AUDIT_ACTION_AUTH_TRUSTED_DEVICE_REVOKE_ALL,
    }
    missing = required - BANNER_ELIGIBLE_ACTIONS
    assert not missing, (
        f"banner-eligible registry missing NFR-011-005 targets: "
        f"{sorted(missing)} — update "
        "echoroo.services.user_banner.BANNER_ELIGIBLE_ACTIONS"
    )
