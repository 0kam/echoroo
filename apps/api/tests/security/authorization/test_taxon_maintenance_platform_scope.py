"""Platform-scope gate coverage for the taxon-catalog maintenance actions.

The two admin maintenance triggers (``platform.taxon.seed_birdnet`` and
``platform.taxon.sync_vernacular``) are platform-scope superuser-only actions.
They mirror ``platform.iucn.force_resync`` and must therefore route through
the Step-0a branch of :func:`echoroo.core.permissions.is_allowed`:

* session (cookie / JWT) superuser  -> allowed;
* API-key superuser principal       -> denied (Step -1 universal veto);
* authenticated non-superuser       -> denied.

Pure-function gate tests — no DB, no FastAPI app.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from echoroo.core.actions import (
    PLATFORM_TAXON_SEED_BIRDNET_ACTION,
    PLATFORM_TAXON_SYNC_VERNACULAR_ACTION,
)
from echoroo.core.permissions import is_allowed

_TAXON_MAINTENANCE_ACTIONS = (
    PLATFORM_TAXON_SEED_BIRDNET_ACTION,
    PLATFORM_TAXON_SYNC_VERNACULAR_ACTION,
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
        for action in _TAXON_MAINTENANCE_ACTIONS:
            assert action.is_platform_scope is True
            assert action.is_superuser_only is True
            assert action.required_permission is None
            assert action.is_mutating is True

    @pytest.mark.parametrize("action", _TAXON_MAINTENANCE_ACTIONS)
    def test_session_superuser_allowed(self, action: object) -> None:
        allowed, _ = is_allowed(
            action=action,  # type: ignore[arg-type]
            user=_session_superuser(),
            project=None,  # platform-scope ignores project
        )
        assert allowed is True

    @pytest.mark.parametrize("action", _TAXON_MAINTENANCE_ACTIONS)
    def test_api_key_superuser_denied(self, action: object) -> None:
        allowed, _ = is_allowed(
            action=action,  # type: ignore[arg-type]
            user=_api_key_superuser(),
            project=None,
        )
        assert allowed is False

    @pytest.mark.parametrize("action", _TAXON_MAINTENANCE_ACTIONS)
    def test_authenticated_non_superuser_denied(self, action: object) -> None:
        allowed, _ = is_allowed(
            action=action,  # type: ignore[arg-type]
            user=_session_authenticated(),
            project=None,
        )
        assert allowed is False
