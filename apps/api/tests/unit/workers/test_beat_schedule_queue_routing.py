"""Every beat-scheduled task must land on a queue a worker consumes.

Regression guard for the silent ``drain-outbox-events`` outage found on
2026-09-21: :mod:`echoroo.workers.outbox_processor` declared
``queue="worker-cpu"`` — the *container* name of the CPU worker, not a
queue name. The CPU worker subscribes to ``-Q default`` and the GPU
worker to ``-Q gpu``, so nothing consumed ``worker-cpu``. Beat happily
dispatched the task every 30s and the messages piled up unread in Redis
(251,160 of them, ~250 MB, by the time it was noticed) while the outbox
never drained.

Celery gives no warning for this: publishing to a queue with no
consumer is perfectly legal AMQP/Redis. The only defence is asserting
the routing statically, which is what this module does.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from echoroo.workers.celery_app import app

# Queues the compose workers actually consume. Kept as a literal so the
# test still protects CI images that do not ship compose.dev.yaml; the
# ``test_consumed_queues_match_compose`` case below asserts the literal
# has not drifted from the real compose file whenever it is available.
CONSUMED_QUEUES = frozenset({"default", "gpu"})

# ``-Q a,b`` on a celery worker command line.
_DASH_Q = re.compile(r"-Q\s+([A-Za-z0-9_,.-]+)")


def _repo_root() -> Path | None:
    """Walk up from this file looking for ``compose.dev.yaml``.

    Returns ``None`` when the file is absent — the test tree is copied
    without the repo root in some execution environments (container
    ``/tmp`` copies, sdist installs), and the literal above is the
    authority there.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "compose.dev.yaml").is_file():
            return parent
    return None


def _queue_for(task_name: str) -> str:
    """Resolve the queue a beat dispatch of ``task_name`` would publish to.

    Mirrors ``celery.beat.Scheduler.apply_async``: the task object is
    looked up in the registry (beat imports every module in
    ``app.conf.include``) and dispatched via ``task.apply_async``, so the
    task's own ``queue`` attribute wins over ``task_default_queue``.
    ``task_routes`` is consulted first, matching Celery's own order.
    """
    route = app.conf.task_routes.get(task_name) if app.conf.task_routes else None
    if route and route.get("queue"):
        return str(route["queue"])

    # Celery imports ``app.conf.include`` lazily at worker/beat start, so
    # in-process the registry is empty until the owning module is
    # imported. Import just that one module (rather than every include,
    # which would drag in TensorFlow) to populate ``app.tasks``.
    module_path, _, _ = task_name.rpartition(".")
    assert module_path in app.conf.include, (
        f"{task_name} is in beat_schedule but {module_path} is not in "
        f"app.conf.include — beat could never dispatch it."
    )
    importlib.import_module(module_path)

    task = app.tasks.get(task_name)
    assert task is not None, (
        f"{module_path} does not register a task named {task_name!r}; "
        f"the beat entry would fail to resolve. Check the ``name=`` "
        f"argument on the task decorator."
    )
    queue = getattr(task, "queue", None)
    return str(queue) if queue else str(app.conf.task_default_queue)


@pytest.mark.parametrize(
    "entry_name",
    sorted(app.conf.beat_schedule),
)
def test_beat_task_routes_to_a_consumed_queue(entry_name: str) -> None:
    task_name = app.conf.beat_schedule[entry_name]["task"]
    queue = _queue_for(task_name)

    assert queue in CONSUMED_QUEUES, (
        f"beat entry {entry_name!r} dispatches {task_name} to queue "
        f"{queue!r}, which no worker consumes (consumed: "
        f"{sorted(CONSUMED_QUEUES)}). The task would be published and "
        f"never executed. Drop the ``queue=`` argument from the task "
        f"declaration, or subscribe a worker to {queue!r} in "
        f"compose.dev.yaml and add it to CONSUMED_QUEUES here."
    )


def test_consumed_queues_match_compose() -> None:
    """The literal above must stay in sync with compose.dev.yaml ``-Q``."""
    root = _repo_root()
    if root is None:
        pytest.skip("compose.dev.yaml not reachable from the test tree")

    compose = (root / "compose.dev.yaml").read_text(encoding="utf-8")
    from_compose = {
        queue
        for match in _DASH_Q.findall(compose)
        for queue in match.split(",")
        if queue
    }

    assert from_compose == set(CONSUMED_QUEUES), (
        f"compose.dev.yaml workers consume {sorted(from_compose)} but "
        f"CONSUMED_QUEUES says {sorted(CONSUMED_QUEUES)}. Update the "
        f"constant in this module to match."
    )
