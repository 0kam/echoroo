"""Compare the keyring state loaded by the API and Celery workers."""

from __future__ import annotations

import argparse
from typing import Any

import httpx

celery_app: Any | None = None


def compare_states(
    api_state: str | None,
    worker_replies: dict[str, Any] | None,
    *,
    expected_workers: int | None = None,
) -> list[str]:
    """Return consumer problems found in an API/worker state comparison."""
    problems: list[str] = []
    if api_state is None:
        problems.append("api: missing keyring state")

    if not worker_replies:
        problems.append("workers: no workers answered")
        worker_count = 0
    else:
        worker_count = len(worker_replies)

    if expected_workers is not None and worker_count != expected_workers:
        problems.append(
            f"workers: expected {expected_workers} distinct workers, got {worker_count}"
        )

    if not worker_replies:
        return problems

    for hostname, reply in sorted(worker_replies.items(), key=lambda item: str(item[0])):
        name = str(hostname)
        if not isinstance(reply, dict):
            problems.append(f"{name}: error")
            continue
        if "error" in reply:
            error = reply["error"]
            if isinstance(error, str):
                problems.append(f"{name}: error {error}")
            else:
                problems.append(f"{name}: error")
            continue
        state = reply.get("state")
        if not isinstance(state, str):
            problems.append(f"{name}: missing keyring state")
            continue
        if api_state is not None and state != api_state:
            problems.append(f"{name}: state {state} (expected {api_state})")
    return problems


def _api_state(api_url: str, timeout: float) -> str | None:
    """Fetch the API's readiness state, hiding response details from callers."""
    response = httpx.get(f"{api_url.rstrip('/')}/health/ready", timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return None
    state = payload.get("keyring_state")
    return state if isinstance(state, str) else None


def _celery_application() -> Any:
    """Load the Celery application lazily so the CLI can query the API first."""
    global celery_app
    if celery_app is None:
        from echoroo.workers.celery_app import app

        celery_app = app
    return celery_app


def _worker_replies(timeout: float) -> dict[str, Any] | None:
    """Query workers through Celery remote control."""
    replies = _celery_application().control.broadcast(
        "keyring_status",
        reply=True,
        timeout=timeout,
    )
    if not isinstance(replies, list):
        return None

    merged: dict[str, Any] = {}
    for worker_reply in replies:
        if not isinstance(worker_reply, dict):
            continue
        for hostname, reply in worker_reply.items():
            merged[str(hostname)] = reply
    return merged


def _positive_int(value: str) -> int:
    """Parse a positive integer command-line argument."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    """Build the activation-check argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--expected-workers",
        required=True,
        type=_positive_int,
        help="Expected number of distinct running Celery workers.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the activation barrier check and return its process exit code."""
    args = _build_parser().parse_args(argv)
    if args.timeout <= 0:
        print("timeout must be greater than zero")
        return 1

    api_error = False
    try:
        api_state = _api_state(args.api_url, args.timeout)
    except Exception:  # noqa: BLE001 — the CLI reports only the consumer name
        api_state = None
        api_error = True

    workers_error = False
    try:
        worker_replies = _worker_replies(args.timeout)
    except Exception:  # noqa: BLE001 — the CLI reports only the consumer name
        worker_replies = None
        workers_error = True

    problems = compare_states(
        api_state,
        worker_replies,
        expected_workers=args.expected_workers,
    )
    if api_error:
        problems = [problem for problem in problems if problem != "api: missing keyring state"]
        problems.insert(0, "api: error")
    if workers_error:
        problems = [problem for problem in problems if problem != "workers: no workers answered"]
        problems.append("workers: error")

    if problems:
        for problem in problems:
            print(problem)
        return 1

    assert api_state is not None
    print(f"api: {api_state}")
    assert worker_replies is not None
    for hostname, reply in sorted(worker_replies.items(), key=lambda item: str(item[0])):
        assert isinstance(reply, dict)
        state = reply.get("state")
        assert isinstance(state, str)
        print(f"{hostname}: {state}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
