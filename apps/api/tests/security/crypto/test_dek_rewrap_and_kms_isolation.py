"""Security checks for keyring rewrap and AWS SDK isolation."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

import pytest

from echoroo.core import kms
from echoroo.core.keyring import KeyringKeyError


def _load_rewrap_script() -> object:
    """Load the repository rewrap script without making scripts a package."""
    script_path = Path(__file__).resolve().parents[5] / "scripts" / "rewrap_dek.py"
    spec = importlib.util.spec_from_file_location("rewrap_dek_test", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("rewrap script could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_keyring_rewrap_old_to_new(select_keys: Any) -> None:
    select = select_keys
    select(
        KEYRING_TOTP_KEY="test-totp-wrap",
        KEYRING_TOTP_KEY_VERSION=2,
        KEYRING_TOTP_KEY_OLD="test-totp-wrap-old",
        KEYRING_TOTP_KEY_VERSION_OLD=1,
    )
    plaintext = b"d" * 32
    wrapped = kms.wrap_dek(plaintext, key_id="test-totp-wrap-old")

    rewrapped = kms.rewrap_dek(
        wrapped,
        source_key_id="test-totp-wrap-old",
        destination_key_id="test-totp-wrap",
    )

    assert kms.unwrap_dek(rewrapped, key_id="test-totp-wrap") == plaintext
    with pytest.raises(KeyringKeyError):
        kms.unwrap_dek(rewrapped, key_id="test-totp-wrap-old")


def test_rewrap_script_refuses_mismatched_selectors(select_keys: Any) -> None:
    select = select_keys
    select(
        KEYRING_TOTP_KEY="test-totp-wrap",
        KEYRING_TOTP_KEY_VERSION=2,
        KEYRING_TOTP_KEY_OLD="test-totp-wrap-old",
        KEYRING_TOTP_KEY_VERSION_OLD=1,
    )
    script = _load_rewrap_script()

    result = asyncio.run(
        script._amain(  # type: ignore[attr-defined]
            [
                "--source-key-id",
                "test-totp-wrap-old",
                "--target-key-id",
                "wrong-key",
                "--old-version",
                "1",
                "--new-version",
                "2",
                "--dry-run",
            ]
        )
    )

    assert result == 2


def test_aws_sdk_lint_finds_no_imports() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    import sys

    sys.path.insert(0, str(repo_root / "scripts"))
    import lint_s3_isolation

    assert not lint_s3_isolation.find_violations(repo_root / "apps/api/echoroo")
    assert not lint_s3_isolation.find_violations(repo_root / "scripts")
