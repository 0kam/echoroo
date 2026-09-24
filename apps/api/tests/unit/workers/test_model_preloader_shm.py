"""Tests for the /dev/shm capacity check run when a gpu-queue worker starts."""

from __future__ import annotations

import logging
from collections import namedtuple
from types import SimpleNamespace

import pytest

from echoroo.workers import model_preloader

_Usage = namedtuple("_Usage", ["total", "used", "free"])


def test_required_shm_bytes_gpu_mode_uses_configured_workers() -> None:
    # 2 slots x 16 segments x 160_000 samples x 4 bytes.
    assert (
        model_preloader.required_shm_bytes(use_gpu=True, batch_size=16, workers=1)
        == 2 * 16 * 160_000 * 4
    )


def test_required_shm_bytes_cpu_mode_uses_physical_cores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_preloader, "_physical_cpu_count", lambda: 12)
    # workers is ignored in CPU mode: birdnet runs one worker per core.
    assert (
        model_preloader.required_shm_bytes(use_gpu=False, batch_size=16, workers=1)
        == 24 * 16 * 160_000 * 4
    )


def _patch(monkeypatch: pytest.MonkeyPatch, *, shm_total: int) -> None:
    settings = SimpleNamespace(ML_USE_GPU=False, ML_GPU_BATCH_SIZE=16, ML_WORKERS=1)
    monkeypatch.setattr("echoroo.core.settings.get_settings", lambda: settings)
    monkeypatch.setattr(model_preloader, "_physical_cpu_count", lambda: 12)
    monkeypatch.setattr(
        model_preloader.shutil,
        "disk_usage",
        lambda _path: _Usage(shm_total, 0, shm_total),
    )


def test_check_shm_capacity_warns_on_docker_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch(monkeypatch, shm_total=64 * 2**20)
    with caplog.at_level(logging.WARNING, logger=model_preloader.__name__):
        model_preloader.check_shm_capacity()
    assert "/dev/shm is 64 MiB" in caplog.text
    assert "ECHOROO_WORKER_SHM_SIZE" in caplog.text


def test_check_shm_capacity_silent_when_large_enough(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch(monkeypatch, shm_total=2 * 2**30)
    with caplog.at_level(logging.WARNING, logger=model_preloader.__name__):
        model_preloader.check_shm_capacity()
    assert caplog.text == ""
