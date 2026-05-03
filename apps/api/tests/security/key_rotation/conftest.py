"""Phase 17 A-1 / T977: isolation fixture for the moto-based KMS suite.

The ``echoroo-backend`` dev container exports
``AWS_ENDPOINT_URL_KMS=http://localstack:4566`` so the production
``boto3`` client speaks to the in-cluster LocalStack instance.  The
``moto.mock_aws()`` context manager interposes a Python-level fake
AWS API only when boto3 falls back to its default endpoint discovery.
With ``AWS_ENDPOINT_URL_KMS`` set, boto3 dispatches to LocalStack
*through* the mock — so state leaks across tests (alias names from
one test reappear as ``AlreadyExistsException`` in the next).

Auto-applied to every test under ``tests/security/key_rotation`` to
remove the LocalStack-pointing endpoint variables for the duration
of the test, restoring the moto in-process isolation contract.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_kms_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop AWS endpoint env vars so moto's in-process fake takes over."""
    for env_var in (
        "AWS_ENDPOINT_URL_KMS",
        "AWS_ENDPOINT_URL",
        "S3_ENDPOINT_URL",
    ):
        monkeypatch.delenv(env_var, raising=False)
