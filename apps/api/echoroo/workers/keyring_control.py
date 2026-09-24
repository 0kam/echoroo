"""Celery remote-control and process-hardening hooks for the local keyring."""

from __future__ import annotations

from typing import Any

from celery.signals import worker_process_init
from celery.worker.control import inspect_command

from echoroo.core import keyring


@inspect_command(name="keyring_status")  # type: ignore[untyped-decorator]
def keyring_status(state: Any, **_kwargs: Any) -> dict[str, object]:
    """Return the worker's cached keyring status without key material."""
    del state
    try:
        return keyring.keyring_status()
    except keyring.KeyringError as exc:
        return {"error": exc.__class__.__name__}


@worker_process_init.connect  # type: ignore[untyped-decorator]
def _harden_worker_process(**_kwargs: object) -> None:
    """Disable dumpability in every prefork child before tasks run."""
    keyring.harden_process()


__all__ = ["keyring_status"]
