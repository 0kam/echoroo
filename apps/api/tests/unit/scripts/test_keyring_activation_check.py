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


def test_compare_states_requires_expected_worker_count() -> None:
    assert check.compare_states(
        "0123456789abcdef",
        {"worker-a": {"state": "0123456789abcdef"}},
        expected_workers=2,
    ) == ["workers: expected 2 distinct workers, got 1"]


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

    class _Control:
        def broadcast(
            self,
            command: str,
            arguments: Any = None,
            destination: Any = None,
            pattern: Any = None,
            matcher: Any = None,
            connection: Any = None,
            reply: bool = False,
            timeout: float = 1.0,
            limit: Any = None,
            callback: Any = None,
            channel: Any = None,
            headers: Any = None,
            **kwargs: Any,
        ) -> list[dict[str, dict[str, str]]]:
            del arguments, destination, pattern, matcher, connection, limit
            del callback, channel, headers, kwargs
            assert command == "keyring_status"
            assert reply is True
            assert timeout == 2.0
            return [{"worker-a": {"state": "0123456789abcdef"}}]

    monkeypatch.setattr(check, "celery_app", SimpleNamespace(control=_Control()))

    assert check.main(["--timeout", "2", "--expected-workers", "1"]) == 0
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

    assert check.main(["--expected-workers", "1"]) == 1
    assert capsys.readouterr().out.strip() == (
        "worker-a: state fedcba9876543210 (expected 0123456789abcdef)"
    )


def test_main_fails_for_missing_worker(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(check, "_api_state", lambda _url, _timeout: "0123456789abcdef")
    monkeypatch.setattr(check, "_worker_replies", lambda _timeout: {})

    assert check.main(["--expected-workers", "1"]) == 1
    assert "got 0" in capsys.readouterr().out


def test_main_fails_for_extra_worker(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(check, "_api_state", lambda _url, _timeout: "0123456789abcdef")
    monkeypatch.setattr(
        check,
        "_worker_replies",
        lambda _timeout: {
            "worker-a": {"state": "0123456789abcdef"},
            "worker-b": {"state": "0123456789abcdef"},
        },
    )

    assert check.main(["--expected-workers", "1"]) == 1
    assert "expected 1 distinct workers, got 2" in capsys.readouterr().out


def test_worker_replies_merge_broadcast_replies(monkeypatch: Any) -> None:
    from celery import Celery

    app = Celery("keyring-activation-test", broker="memory://")
    calls: list[dict[str, Any]] = []

    def _transport_broadcast(
        self: Any,
        command: str,
        arguments: Any,
        destination: Any,
        reply: bool,
        timeout: float,
        limit: Any,
        callback: Any,
        *,
        channel: Any = None,
        pattern: Any = None,
        matcher: Any = None,
    ) -> Any:
        del self
        calls.append(
            {
                "command": command,
                "arguments": arguments,
                "destination": destination,
                "reply": reply,
                "timeout": timeout,
                "limit": limit,
                "callback": callback,
                "channel": channel,
                "pattern": pattern,
                "matcher": matcher,
            }
        )
        return [
            {"worker-a": {"state": "a"}},
            {"worker-b": {"state": "b"}},
        ]

    monkeypatch.setattr(type(app.control.mailbox), "_broadcast", _transport_broadcast)
    monkeypatch.setattr(check, "celery_app", app)
    assert check._worker_replies(3.0) == {
        "worker-a": {"state": "a"},
        "worker-b": {"state": "b"},
    }
    assert calls[0]["command"] == "keyring_status"
    assert calls[0]["reply"] is True
    assert calls[0]["timeout"] == 3.0


def test_main_fails_for_worker_error_reply(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(check, "_api_state", lambda _url, _timeout: "0123456789abcdef")
    monkeypatch.setattr(
        check,
        "_worker_replies",
        lambda _timeout: {"worker-a": {"error": "KeyringConfigError"}},
    )

    assert check.main(["--expected-workers", "1"]) == 1
    assert capsys.readouterr().out.strip() == "worker-a: error KeyringConfigError"
