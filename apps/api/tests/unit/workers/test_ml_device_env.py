"""Unit tests for ``echoroo.workers.ml_device_env``.

Covers every branch of :func:`apply_ml_device_env` without importing
TensorFlow, numpy, or touching the database.  ``get_settings`` is stubbed
via ``monkeypatch`` using the same ``_StubSettings`` pattern as
``test_celery_app_coverage_uplift.py``.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CPU_THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    "TF_NUM_INTRAOP_THREADS",
    "TF_NUM_INTEROP_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)

_ALL_OBSERVED_VARS = (
    "CUDA_VISIBLE_DEVICES",
    "TF_FORCE_GPU_ALLOW_GROWTH",
) + _CPU_THREAD_ENV_VARS


def _stub_settings(**kwargs: object) -> SimpleNamespace:
    """Return a SimpleNamespace that looks like Settings for apply_ml_device_env."""
    defaults: dict[str, object] = {
        "ML_USE_GPU": False,
        "ML_CPU_NUM_THREADS": 4,
        "ML_GPU_ALLOW_GROWTH": False,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _patch_settings(monkeypatch: pytest.MonkeyPatch, stub: SimpleNamespace) -> None:
    from echoroo.core import settings as settings_mod

    monkeypatch.setattr(settings_mod, "get_settings", lambda: stub)


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all ML-related env vars so each test starts from a clean slate."""
    for var in _ALL_OBSERVED_VARS:
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# CPU mode
# ---------------------------------------------------------------------------


def test_cpu_mode_sets_cuda_visible_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    """CPU mode forces CUDA_VISIBLE_DEVICES=-1."""
    _clean_env(monkeypatch)
    stub = _stub_settings(ML_USE_GPU=False, ML_CPU_NUM_THREADS=4)
    _patch_settings(monkeypatch, stub)

    from echoroo.workers.ml_device_env import apply_ml_device_env

    apply_ml_device_env()

    assert os.environ["CUDA_VISIBLE_DEVICES"] == "-1"


def test_cpu_mode_sets_all_thread_cap_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """CPU mode sets all six thread-pool variables to ML_CPU_NUM_THREADS."""
    _clean_env(monkeypatch)
    stub = _stub_settings(ML_USE_GPU=False, ML_CPU_NUM_THREADS=2)
    _patch_settings(monkeypatch, stub)

    from echoroo.workers.ml_device_env import apply_ml_device_env

    apply_ml_device_env()

    for var in _CPU_THREAD_ENV_VARS:
        assert os.environ.get(var) == "2", f"{var} expected '2', got {os.environ.get(var)!r}"


def test_cpu_mode_does_not_set_tf_force_gpu_allow_growth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CPU mode must not touch TF_FORCE_GPU_ALLOW_GROWTH."""
    _clean_env(monkeypatch)
    stub = _stub_settings(ML_USE_GPU=False)
    _patch_settings(monkeypatch, stub)

    from echoroo.workers.ml_device_env import apply_ml_device_env

    apply_ml_device_env()

    assert "TF_FORCE_GPU_ALLOW_GROWTH" not in os.environ


# ---------------------------------------------------------------------------
# setdefault semantics (CPU mode)
# ---------------------------------------------------------------------------


def test_cpu_mode_does_not_overwrite_preexisting_thread_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-existing OMP_NUM_THREADS must survive apply_ml_device_env (setdefault)."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("OMP_NUM_THREADS", "2")
    stub = _stub_settings(ML_USE_GPU=False, ML_CPU_NUM_THREADS=8)
    _patch_settings(monkeypatch, stub)

    from echoroo.workers.ml_device_env import apply_ml_device_env

    apply_ml_device_env()

    # Operator value must win.
    assert os.environ["OMP_NUM_THREADS"] == "2"
    # Other vars still get the cap.
    for var in _CPU_THREAD_ENV_VARS:
        if var != "OMP_NUM_THREADS":
            assert os.environ.get(var) == "8", f"{var} expected '8'"


# ---------------------------------------------------------------------------
# Idempotency (CPU mode)
# ---------------------------------------------------------------------------


def test_cpu_mode_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling apply_ml_device_env twice in CPU mode is safe and stable."""
    _clean_env(monkeypatch)
    stub = _stub_settings(ML_USE_GPU=False, ML_CPU_NUM_THREADS=3)
    _patch_settings(monkeypatch, stub)

    from echoroo.workers.ml_device_env import apply_ml_device_env

    apply_ml_device_env()
    snapshot = {v: os.environ.get(v) for v in _ALL_OBSERVED_VARS}

    apply_ml_device_env()
    for var in _ALL_OBSERVED_VARS:
        assert os.environ.get(var) == snapshot[var], (
            f"{var} changed on second call"
        )


# ---------------------------------------------------------------------------
# GPU mode
# ---------------------------------------------------------------------------


def test_gpu_mode_does_not_set_cuda_visible_devices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GPU mode must NOT set CUDA_VISIBLE_DEVICES."""
    _clean_env(monkeypatch)
    stub = _stub_settings(ML_USE_GPU=True, ML_GPU_ALLOW_GROWTH=False)
    _patch_settings(monkeypatch, stub)

    from echoroo.workers.ml_device_env import apply_ml_device_env

    apply_ml_device_env()

    assert "CUDA_VISIBLE_DEVICES" not in os.environ


def test_gpu_mode_does_not_set_thread_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    """GPU mode must NOT set any thread-cap variables."""
    _clean_env(monkeypatch)
    stub = _stub_settings(ML_USE_GPU=True, ML_GPU_ALLOW_GROWTH=False)
    _patch_settings(monkeypatch, stub)

    from echoroo.workers.ml_device_env import apply_ml_device_env

    apply_ml_device_env()

    for var in _CPU_THREAD_ENV_VARS:
        assert var not in os.environ, f"{var} must not be set in GPU mode"


def test_gpu_mode_allow_growth_true_sets_tf_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GPU mode with ML_GPU_ALLOW_GROWTH=True sets TF_FORCE_GPU_ALLOW_GROWTH=true."""
    _clean_env(monkeypatch)
    stub = _stub_settings(ML_USE_GPU=True, ML_GPU_ALLOW_GROWTH=True)
    _patch_settings(monkeypatch, stub)

    from echoroo.workers.ml_device_env import apply_ml_device_env

    apply_ml_device_env()

    assert os.environ.get("TF_FORCE_GPU_ALLOW_GROWTH") == "true"


def test_gpu_mode_allow_growth_false_does_not_set_tf_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GPU mode with ML_GPU_ALLOW_GROWTH=False must NOT set TF_FORCE_GPU_ALLOW_GROWTH."""
    _clean_env(monkeypatch)
    stub = _stub_settings(ML_USE_GPU=True, ML_GPU_ALLOW_GROWTH=False)
    _patch_settings(monkeypatch, stub)

    from echoroo.workers.ml_device_env import apply_ml_device_env

    apply_ml_device_env()

    assert "TF_FORCE_GPU_ALLOW_GROWTH" not in os.environ


def test_gpu_mode_allow_growth_does_not_overwrite_preexisting_tf_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ML_GPU_ALLOW_GROWTH=True uses setdefault: pre-existing value is preserved."""
    _clean_env(monkeypatch)
    monkeypatch.setenv("TF_FORCE_GPU_ALLOW_GROWTH", "false")
    stub = _stub_settings(ML_USE_GPU=True, ML_GPU_ALLOW_GROWTH=True)
    _patch_settings(monkeypatch, stub)

    from echoroo.workers.ml_device_env import apply_ml_device_env

    apply_ml_device_env()

    assert os.environ["TF_FORCE_GPU_ALLOW_GROWTH"] == "false"


# ---------------------------------------------------------------------------
# Idempotency (GPU mode)
# ---------------------------------------------------------------------------


def test_gpu_mode_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling apply_ml_device_env twice in GPU mode is safe and stable."""
    _clean_env(monkeypatch)
    stub = _stub_settings(ML_USE_GPU=True, ML_GPU_ALLOW_GROWTH=True)
    _patch_settings(monkeypatch, stub)

    from echoroo.workers.ml_device_env import apply_ml_device_env

    apply_ml_device_env()
    snapshot = {v: os.environ.get(v) for v in _ALL_OBSERVED_VARS}

    apply_ml_device_env()
    for var in _ALL_OBSERVED_VARS:
        assert os.environ.get(var) == snapshot[var], (
            f"{var} changed on second call"
        )
