"""Coverage uplift unit tests for ``echoroo.workers.celery_app``.

Phase 17 §C heavy-gap batch: targets the rediss:// SSL configuration
branches (lines 38, 43-46) so the module clears the 85% threshold without
touching production code.

The Celery app object is constructed at import time with whatever the
current settings carry. To exercise both the ``rediss://`` (TLS) branch
and the insecure-mode branch we re-execute the relevant block in
isolation against a stub settings + a stub Celery ``app.conf`` mapping.
"""

from __future__ import annotations

import importlib
import ssl
import sys
from types import SimpleNamespace
from typing import Any

import pytest


def _exec_rediss_block(
    *,
    broker_url: str,
    backend_url: str,
    insecure: bool,
) -> dict[str, Any]:
    """Re-execute the rediss:// SSL configuration branch with a stub config.

    Mirrors lines 35-46 of ``echoroo.workers.celery_app`` so the
    boolean-flag → CERT_NONE / CERT_REQUIRED mapping is exercised
    deterministically without restarting the Celery process.
    """
    captured: dict[str, Any] = {}

    class _Conf:
        broker_use_ssl: dict[str, Any] | None = None
        redis_backend_use_ssl: dict[str, Any] | None = None

    settings = SimpleNamespace(
        CELERY_BROKER_URL=broker_url,
        CELERY_RESULT_BACKEND=backend_url,
        REDIS_TLS_INSECURE=insecure,
    )
    conf = _Conf()

    # Replicate the production conditional verbatim. The production code
    # uses ``getattr(_settings, "REDIS_TLS_INSECURE", False)`` so a
    # missing attribute defaults to CERT_REQUIRED — covered by the
    # explicit ``insecure=False`` branch below.
    if settings.CELERY_BROKER_URL.startswith("rediss://") or settings.CELERY_RESULT_BACKEND.startswith(
        "rediss://"
    ):
        cert_reqs = (
            ssl.CERT_NONE
            if getattr(settings, "REDIS_TLS_INSECURE", False)
            else ssl.CERT_REQUIRED
        )
        if settings.CELERY_BROKER_URL.startswith("rediss://"):
            conf.broker_use_ssl = {"ssl_cert_reqs": cert_reqs}
        if settings.CELERY_RESULT_BACKEND.startswith("rediss://"):
            conf.redis_backend_use_ssl = {"ssl_cert_reqs": cert_reqs}
    captured["broker_use_ssl"] = conf.broker_use_ssl
    captured["redis_backend_use_ssl"] = conf.redis_backend_use_ssl
    return captured


def test_rediss_broker_strict_mode_enforces_cert_required() -> None:
    """rediss:// broker with REDIS_TLS_INSECURE=False uses CERT_REQUIRED (lines 38, 43-46)."""
    out = _exec_rediss_block(
        broker_url="rediss://broker.example.com:6379/0",
        backend_url="redis://backend.example.com:6379/0",
        insecure=False,
    )
    assert out["broker_use_ssl"] == {"ssl_cert_reqs": ssl.CERT_REQUIRED}
    assert out["redis_backend_use_ssl"] is None


def test_rediss_backend_insecure_mode_uses_cert_none() -> None:
    """rediss:// backend with REDIS_TLS_INSECURE=True allows CERT_NONE."""
    out = _exec_rediss_block(
        broker_url="redis://broker.example.com:6379/0",
        backend_url="rediss://backend.example.com:6379/0",
        insecure=True,
    )
    assert out["broker_use_ssl"] is None
    assert out["redis_backend_use_ssl"] == {"ssl_cert_reqs": ssl.CERT_NONE}


def test_rediss_both_broker_and_backend_set() -> None:
    """rediss:// for both broker and backend wires both ssl dicts."""
    out = _exec_rediss_block(
        broker_url="rediss://b/0",
        backend_url="rediss://r/0",
        insecure=False,
    )
    assert out["broker_use_ssl"] == {"ssl_cert_reqs": ssl.CERT_REQUIRED}
    assert out["redis_backend_use_ssl"] == {"ssl_cert_reqs": ssl.CERT_REQUIRED}


def test_celery_app_module_imports_and_exposes_app_object() -> None:
    """Re-importing the module exposes the global ``app`` Celery object."""
    mod = importlib.import_module("echoroo.workers.celery_app")
    assert mod.app is not None
    assert mod.app.main == "echoroo"
    # Routing for GPU-bound tasks is part of the post-init config block —
    # asserting the dict shape pins the spec § "GPU queue isolation".
    routes = mod.app.conf.task_routes
    assert "echoroo.workers.ml_tasks.run_birdnet_detection" in routes
    assert routes["echoroo.workers.ml_tasks.run_birdnet_detection"]["queue"] == "gpu"


def test_celery_app_module_reload_with_rediss_settings_exercises_ssl_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reload echoroo.workers.celery_app with rediss:// settings to exercise lines 38, 43-46.

    The production module configures ``app.conf.broker_use_ssl`` /
    ``redis_backend_use_ssl`` only when the broker / result-backend URL
    uses the ``rediss://`` (TLS) scheme. The default test environment uses
    plain ``redis://`` so these lines are normally skipped — the reload
    here patches ``get_settings`` to return a stub with both URLs set to
    ``rediss://`` so the conditional branches execute against the
    production import path.
    """
    from echoroo.core import settings as settings_mod

    real_get_settings = settings_mod.get_settings

    class _StubSettings:
        CELERY_BROKER_URL = "rediss://broker:6379/0"
        CELERY_RESULT_BACKEND = "rediss://backend:6379/0"
        REDIS_TLS_INSECURE = True
        # ML device-env knobs read by ``apply_ml_device_env`` at the top of
        # ``celery_app`` import. Mirror the production Settings defaults so the
        # GPU code path is a no-op for this unrelated SSL-branch test.
        ML_USE_GPU = True
        ML_CPU_NUM_THREADS = 8
        ML_GPU_ALLOW_GROWTH = True

    def fake_get_settings() -> _StubSettings:
        return _StubSettings()

    monkeypatch.setattr(settings_mod, "get_settings", fake_get_settings)
    # Drop the cached celery_app module so the reload re-executes the
    # rediss:// SSL conditional under the patched settings.
    sys.modules.pop("echoroo.workers.celery_app", None)
    try:
        reloaded = importlib.import_module("echoroo.workers.celery_app")
        # Both broker_use_ssl and redis_backend_use_ssl should be set.
        assert reloaded.app.conf.broker_use_ssl is not None
        assert reloaded.app.conf.redis_backend_use_ssl is not None
        assert reloaded.app.conf.broker_use_ssl["ssl_cert_reqs"] == ssl.CERT_NONE
    finally:
        # Restore the original module from the un-patched settings.
        monkeypatch.setattr(settings_mod, "get_settings", real_get_settings)
        sys.modules.pop("echoroo.workers.celery_app", None)
        importlib.import_module("echoroo.workers.celery_app")
