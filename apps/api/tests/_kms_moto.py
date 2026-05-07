"""Shared moto-backed KMS provisioning helper for the test suites.

PR-C5 (Phase 17 §C, 2026-05-07): integration and security pytest jobs were
surfacing 9 latent failures (5x ``UnrecognizedClientException``, 4x
``NoCredentialsError``) once PR-C2 unblocked the testcontainer image.
The root cause: neither ``tests/integration/conftest.py`` nor
``tests/security/conftest.py`` provisioned a moto-backed KMS, so any
endpoint that hit ``compute_pii_hash(email)`` (login, password reset,
invitation enumeration, ``confirm_identity``) reached for the real AWS
KMS API and either 401'd against an unrecognised client or hit
``NoCredentialsError``.

The unit suite's :func:`tests.unit.core.test_kms.kms_env` fixture already
demonstrates the canonical pattern (``mock_aws()`` + ``importlib.reload``).
This module factors that pattern out into a single ``provision_moto_kms``
helper used by both the integration and security autouse fixtures.

Design notes:

* The autouse fixtures invoke this helper once per test (function scope).
  ``mock_aws()`` is cheap to enter and re-entry from a nested explicit
  fixture (e.g. :func:`tests.security.key_rotation.test_*.kms_env_pii_rotation`)
  is safely no-op for moto's in-memory backend.
* ``key_rotation/`` already provisions its own CMKs via explicit fixtures
  with overlapping alias names. Calling ``provision_moto_kms`` from the
  security autouse fixture would race against those tests. The autouse
  fixture in :mod:`tests/security/conftest.py` therefore short-circuits
  for items located under ``tests/security/key_rotation/``.
* The companion ``_isolate_kms_endpoint`` autouse fixture under
  ``tests/security/key_rotation/conftest.py`` only deletes endpoint env
  vars; it remains compatible with the security top-level autouse here.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import boto3
import pytest

# Aliases used by tests — kept in sync with scripts/init-localstack.sh and
# the production defaults in ``apps/api/echoroo/core/kms.py``. Production
# code reads these from env vars, so the env wiring below pins each one.
TOTP_DEK_ALIAS = "alias/echoroo-totp-dek"
PII_HASH_ALIAS = "alias/echoroo-pii-hash-hmac"
AUDIT_CHAIN_ALIAS = "alias/echoroo-audit-chain-hmac"
INVITATION_HMAC_ALIAS = "alias/echoroo-invitation-hmac"
INVITATION_HMAC_ALIAS_NEW = "alias/echoroo-invitation-hmac"
INVITATION_HMAC_ALIAS_OLD = "alias/echoroo-invitation-hmac-old"

AWS_REGION = "us-east-1"


def _create_cmk_with_alias(
    kms_client: Any,
    alias_name: str,
    *,
    key_usage: str,
    key_spec: str,
) -> str:
    """Create a CMK + alias in moto and return the canonical KeyId."""
    resp = kms_client.create_key(KeyUsage=key_usage, KeySpec=key_spec)
    key_id = resp["KeyMetadata"]["KeyId"]
    kms_client.create_alias(AliasName=alias_name, TargetKeyId=key_id)
    return str(key_id)


@contextmanager
def provision_moto_kms(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, str]]:
    """Provision a fresh moto-backed KMS and wire env vars for ``echoroo.core.kms``.

    Mirrors :func:`tests.unit.core.test_kms.kms_env`:

    1. Drop any LocalStack endpoint env vars so moto's in-process fake takes over.
    2. Enter ``mock_aws()`` and pin AWS credential / region env vars to dummy
       values so ``boto3`` does not raise ``NoCredentialsError``.
    3. Provision one CMK + alias for each KMS-backed surface
       (TOTP DEK, PII hash, audit chain, invitation HMAC).
    4. Wire the alias env vars production code reads.
    5. Reset ``echoroo.core.kms``'s ``lru_cache``-backed boto3 client so the
       next call constructs a fresh client inside the moto context.

    Yields the alias-to-key-id mapping so callers can drive low-level
    ``GenerateMac`` calls if necessary.
    """
    # 1. Strip endpoint env vars before entering ``mock_aws()`` so moto can
    #    intercept the default regional endpoint. The dev container exports
    #    ``AWS_ENDPOINT_URL_KMS`` pointing at LocalStack, which would
    #    otherwise route through a real service and produce
    #    ``AlreadyExistsException`` from residual state.
    monkeypatch.delenv("AWS_KMS_ENDPOINT", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL_KMS", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    # NB: S3_ENDPOINT_URL is intentionally NOT delenv'd here. This helper
    # only owns KMS isolation; touching the S3 endpoint would surprise
    # any future S3 integration test that expects the LocalStack endpoint
    # to remain pinned. Tests that need S3 isolation should layer their
    # own fixture.

    # ``moto.mock_aws`` is the umbrella decorator/context manager that
    # patches every supported AWS service. Importing here (rather than at
    # module top) keeps the helper safely import-time idempotent for any
    # codepath that does not actually invoke ``provision_moto_kms``.
    from moto import mock_aws

    with mock_aws():
        # 2. Pin AWS credentials + region so boto3 doesn't fail before the
        #    moto interceptor takes over.
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
        monkeypatch.setenv("AWS_DEFAULT_REGION", AWS_REGION)

        client = boto3.client("kms", region_name=AWS_REGION)

        # 3. Provision the canonical CMK set used by every echoroo.core.kms
        #    surface. Each CMK is freshly created per test so state never
        #    leaks across tests in the same session.
        totp_id = _create_cmk_with_alias(
            client,
            TOTP_DEK_ALIAS,
            key_usage="ENCRYPT_DECRYPT",
            key_spec="SYMMETRIC_DEFAULT",
        )
        pii_id = _create_cmk_with_alias(
            client,
            PII_HASH_ALIAS,
            key_usage="GENERATE_VERIFY_MAC",
            key_spec="HMAC_256",
        )
        audit_id = _create_cmk_with_alias(
            client,
            AUDIT_CHAIN_ALIAS,
            key_usage="GENERATE_VERIFY_MAC",
            key_spec="HMAC_256",
        )
        inv_id = _create_cmk_with_alias(
            client,
            INVITATION_HMAC_ALIAS,
            key_usage="GENERATE_VERIFY_MAC",
            key_spec="HMAC_256",
        )

        # 4. Wire the env vars echoroo.core.kms reads. The module honours
        #    several historical names — we set the canonical ones used by
        #    scripts/init-localstack.sh and .env.example.
        monkeypatch.setenv("AWS_KMS_REGION", AWS_REGION)
        monkeypatch.setenv("AWS_KMS_CMK_2FA_ALIAS", TOTP_DEK_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS", PII_HASH_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_AUDIT_CHAIN_ALIAS", AUDIT_CHAIN_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS", INVITATION_HMAC_ALIAS)
        # Phase 17 A-12 / A-8: env-driven kid + alias rotation overrides.
        # Setting the _NEW alias to the same CMK as the legacy alias keeps
        # single-key tests valid (no rotation in flight). Tests that drive
        # rotation explicitly monkeypatch _OLD on top.
        monkeypatch.setenv(
            "AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW", INVITATION_HMAC_ALIAS
        )
        monkeypatch.delenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD", raising=False)
        monkeypatch.setenv("AWS_KMS_CMK_2FA_DEK_ALIAS_NEW", TOTP_DEK_ALIAS)
        monkeypatch.delenv("AWS_KMS_CMK_2FA_DEK_ALIAS_OLD", raising=False)
        # Make sure the v2 PII hash rotation alias is unset so single-key
        # mode is the default (rotation tests opt in explicitly).
        monkeypatch.delenv("AWS_KMS_CMK_PII_HASH_ALIAS_V2", raising=False)

        # 5. Reset the ``lru_cache`` boto3 client so the next call inside
        #    application code constructs a fresh client INSIDE the moto
        #    context. Without this the cached client may have been built
        #    by an earlier test outside moto and would route to real AWS.
        import echoroo.core.kms as kms_module

        # Prefer the explicit reset helper (cheaper than a full module
        # reload + does not invalidate already-imported references). Fall
        # back to ``importlib.reload`` if the helper is missing on an
        # older revision.
        if hasattr(kms_module, "_reset_client_cache"):
            kms_module._reset_client_cache()
        else:  # pragma: no cover — defensive fallback
            importlib.reload(kms_module)

        try:
            yield {
                "totp_id": totp_id,
                "pii_id": pii_id,
                "audit_id": audit_id,
                "inv_id": inv_id,
            }
        finally:
            # Teardown: reset the client cache again so a subsequent test
            # that does NOT use moto (e.g. live-infra tests, if any) gets
            # a fresh client constructed against its own environment.
            if hasattr(kms_module, "_reset_client_cache"):
                kms_module._reset_client_cache()
