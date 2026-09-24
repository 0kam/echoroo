"""PII hash rotation tests for the local keyring selectors."""

from __future__ import annotations

from typing import Any

import pytest

from echoroo.core import kms
from echoroo.core.settings import Settings


def test_v2_selection_dual_writes_both_hashes(select_keys: Any) -> None:
    select = select_keys
    select(KEYRING_PII_KEY_V2="test-pii-hmac-v2")

    hashes = kms.compute_pii_hash_dual("alice@example.com")

    assert set(hashes) == {"v1", "v2"}
    assert hashes["v1"] != hashes["v2"]
    assert kms.get_pii_hash_version() == 2


def test_v1_lookup_keeps_matching_historical_rows(select_keys: Any) -> None:
    historical = kms.compute_pii_hash("alice@example.com")
    select = select_keys
    select(KEYRING_PII_KEY_V2="test-pii-hmac-v2")

    assert kms.verify_pii_hash("alice@example.com", historical)


@pytest.mark.parametrize(
    "variable",
    ["ECHOROO_PII_HASH_ROTATION_COMPLETE", "AWS_" + "KMS_CMK_PII_HASH_ALIAS_V2"],
)
def test_removed_rotation_environment_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
) -> None:
    monkeypatch.setenv(variable, "configuration-value-must-not-be-echoed")

    with pytest.raises(ValueError, match=variable) as exc_info:
        Settings()
    assert "configuration-value-must-not-be-echoed" not in str(exc_info.value)


def test_blank_optional_selectors_are_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose forwards unset optional selectors as empty strings."""
    for variable in ("KEYRING_TOTP_KEY_OLD", "KEYRING_TOTP_KEY_VERSION_OLD", "KEYRING_PII_KEY_V2"):
        monkeypatch.setenv(variable, "")

    settings = Settings()

    assert settings.KEYRING_TOTP_KEY_OLD is None
    assert settings.KEYRING_TOTP_KEY_VERSION_OLD is None
    assert settings.KEYRING_PII_KEY_V2 is None
