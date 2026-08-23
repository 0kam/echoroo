"""Platform-scope gate coverage for the taxon-catalog maintenance actions.

The four admin maintenance triggers (``platform.taxon.seed_birdnet``,
``platform.taxon.sync_vernacular``, ``platform.taxon.load_bundled_vernacular``
and ``platform.taxon.resolve_col_xr``) plus the read-only identity-provenance
action (``platform.taxon.identity_history.read``, WS-A v2 slice 5) are
platform-scope superuser-only actions. They mirror ``platform.iucn.force_resync``
and must therefore route through the Step-0a branch of
:func:`echoroo.core.permissions.is_allowed`:

* session (cookie / JWT) superuser  -> allowed;
* API-key superuser principal       -> denied (Step -1 universal veto);
* authenticated non-superuser       -> denied.

Pure-function gate tests — no DB, no FastAPI app.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from echoroo.core.actions import (
    PLATFORM_TAXON_IDENTITY_HISTORY_READ_ACTION,
    PLATFORM_TAXON_LOAD_BUNDLED_VERNACULAR_ACTION,
    PLATFORM_TAXON_RESOLVE_COL_XR_ACTION,
    PLATFORM_TAXON_SEED_BIRDNET_ACTION,
    PLATFORM_TAXON_SYNC_VERNACULAR_ACTION,
)
from echoroo.core.permissions import is_allowed

#: Mutating triggers. All four rewrite global taxonomy tables.
_TAXON_MAINTENANCE_ACTIONS = (
    PLATFORM_TAXON_SEED_BIRDNET_ACTION,
    PLATFORM_TAXON_SYNC_VERNACULAR_ACTION,
    PLATFORM_TAXON_LOAD_BUNDLED_VERNACULAR_ACTION,
    PLATFORM_TAXON_RESOLVE_COL_XR_ACTION,
)

#: Read-only identity provenance (WS-A v2 slice 5). Same platform-scope
#: superuser-only routing, but ``is_mutating=False``.
_TAXON_IDENTITY_READ_ACTIONS = (PLATFORM_TAXON_IDENTITY_HISTORY_READ_ACTION,)

#: Everything that must route through the Step-0a superuser branch.
_ALL_TAXON_PLATFORM_ACTIONS = (
    *_TAXON_MAINTENANCE_ACTIONS,
    *_TAXON_IDENTITY_READ_ACTIONS,
)


def _session_superuser() -> SimpleNamespace:
    """Cookie/JWT superuser — no ``_api_key_scopes`` attribute, non-member."""
    return SimpleNamespace(
        id="user-superuser-taxon",
        is_superuser=True,
        project_role=None,
    )


def _session_authenticated() -> SimpleNamespace:
    """Cookie/JWT non-superuser."""
    return SimpleNamespace(
        id="user-auth-taxon",
        is_superuser=False,
        project_role=None,
    )


def _api_key_superuser() -> SimpleNamespace:
    """API-key principal owned by a superuser. Step -1 must veto."""
    return SimpleNamespace(
        id="user-superuser-apikey-taxon",
        is_superuser=True,
        project_role=None,
        _api_key_scopes=("view_detection",),
        _api_key_id="apikey-taxon",
        _api_key_project_id=None,
    )


class TestTaxonMaintenancePlatformScope:
    """Step 0a routing for the taxon-catalog maintenance triggers."""

    def test_actions_are_platform_scope_superuser_only(self) -> None:
        for action in _ALL_TAXON_PLATFORM_ACTIONS:
            assert action.is_platform_scope is True
            assert action.is_superuser_only is True
            assert action.required_permission is None

        for action in _TAXON_MAINTENANCE_ACTIONS:
            assert action.is_mutating is True

        # The provenance reads only SELECT: flagging them mutating would make
        # the gate demand step-up/CSRF semantics they do not need.
        for action in _TAXON_IDENTITY_READ_ACTIONS:
            assert action.is_mutating is False

    def test_identity_read_action_name_is_stable(self) -> None:
        """The wire/audit name is part of the contract once shipped."""
        assert (
            PLATFORM_TAXON_IDENTITY_HISTORY_READ_ACTION.name
            == "platform.taxon.identity_history.read"
        )

    @pytest.mark.parametrize("action", _ALL_TAXON_PLATFORM_ACTIONS)
    def test_session_superuser_allowed(self, action: object) -> None:
        allowed, _ = is_allowed(
            action=action,  # type: ignore[arg-type]
            user=_session_superuser(),
            project=None,  # platform-scope ignores project
        )
        assert allowed is True

    @pytest.mark.parametrize("action", _ALL_TAXON_PLATFORM_ACTIONS)
    def test_api_key_superuser_denied(self, action: object) -> None:
        allowed, _ = is_allowed(
            action=action,  # type: ignore[arg-type]
            user=_api_key_superuser(),
            project=None,
        )
        assert allowed is False

    @pytest.mark.parametrize("action", _ALL_TAXON_PLATFORM_ACTIONS)
    def test_authenticated_non_superuser_denied(self, action: object) -> None:
        allowed, _ = is_allowed(
            action=action,  # type: ignore[arg-type]
            user=_session_authenticated(),
            project=None,
        )
        assert allowed is False
