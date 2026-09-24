"""Tests for the keyring activation barrier CLI."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from echoroo.scripts import keyring_activation_check as check


def test_compare_states_all_equal() -> None:
    assert (
        check.compare_states(
            "0123456789abcdef",
            {
                "worker-a": {"state": "0123456789abcdef"},
                "worker-b": {"state": "0123456789abcdef"},
            },
        )
        == []
    )


def test_compare_states_flags_stale_worker() -> None:
    assert check.compare_states(
        "0123456789abcdef",
        {"worker-a": {"state": "fedcba9876543210"}},
    ) == ["worker-a: state fedcba9876543210 (expected 0123456789abcdef)"]


def test_compare_states_flags_worker_error_no_workers_and_missing_api() -> None:
    assert check.compare_states(None, {"worker-a": {"error": "KeyringConfigError"}}) == [
        "api: missing keyring state",
        "worker-a: error KeyringConfigError",
    ]
    assert check.compare_states("0123456789abcdef", {}) == ["workers: no workers answered"]
    assert check.compare_states(None, None) == [
        "api: missing keyring state",
        "workers: no workers answered",
    ]


def test_main_success_prints_only_consumers_and_states(monkeypatch: Any, capsys: Any) -> None:
    def _get(_url: str, *, timeout: float) -> Any:
        del timeout
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"keyring_state": "0123456789abcdef"},
        )

    monkeypatch.setattr(
        check,
        "httpx",
        SimpleNamespace(get=_get),
    )

    class _Inspect:
        def keyring_status(self) -> dict[str, dict[str, str]]:
            return {"worker-a": {"state": "0123456789abcdef"}}

    class _Control:
        def inspect(self, *, timeout: float) -> _Inspect:
            assert timeout == 2.0
            return _Inspect()

    monkeypatch.setattr(check, "celery_app", SimpleNamespace(control=_Control()))

    assert check.main(["--timeout", "2"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "api: 0123456789abcdef",
        "worker-a: 0123456789abcdef",
    ]


def test_main_failure_returns_one(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(
        check,
        "_api_state",
        lambda _url, _timeout: "0123456789abcdef",
    )
    monkeypatch.setattr(
        check,
        "_worker_replies",
        lambda _timeout: {"worker-a": {"state": "fedcba9876543210"}},
    )

    assert check.main([]) == 1
    assert capsys.readouterr().out.strip() == (
        "worker-a: state fedcba9876543210 (expected 0123456789abcdef)"
    )
