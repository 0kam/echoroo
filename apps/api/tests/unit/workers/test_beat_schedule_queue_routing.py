"""Every Celery task must land on a queue a worker consumes.

Regression guard for the silent ``drain-outbox-events`` outage found on
2026-09-21: :mod:`echoroo.workers.outbox_processor` declared
``queue="worker-cpu"`` — the *container* name of the CPU worker, not a
queue name. The CPU worker subscribes to ``-Q default`` and the GPU
worker to ``-Q gpu``, so nothing consumed ``worker-cpu``. Beat happily
dispatched the task every 30s and the messages piled up unread in Redis
(251,160 of them, ~250 MB, by the time it was noticed) while the outbox
never drained. ``audit_log_export.export_weekly`` carried the same
``queue="worker-cpu"`` and was fixed independently in #271.

Celery gives no warning for this: publishing to a queue with no
consumer is perfectly legal AMQP/Redis. The only defence is asserting
the routing statically, which is what this module does, at three
layers:

1. every ``beat_schedule`` entry resolves (Celery's own order:
   ``task_routes`` → task ``queue`` attribute → ``task_default_queue``)
   to a consumed queue;
2. every ``task_routes`` value names a consumed queue;
3. every ``queue=`` keyword on a task decorator anywhere under
   ``echoroo/workers/`` names a consumed queue — found by AST scan so
   tasks that are only ever ``.delay()``-ed (never beat-scheduled) are
   covered too, without importing the heavy ML modules.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

import echoroo.workers
from echoroo.workers.celery_app import app

_WORKERS_DIR = Path(echoroo.workers.__file__).resolve().parent
_TASK_DECORATORS = frozenset({"task", "shared_task"})

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


def test_task_routes_name_consumed_queues() -> None:
    """``task_routes`` is the first thing Celery consults — check it too."""
    for task_name, route in (app.conf.task_routes or {}).items():
        queue = route.get("queue")
        assert queue in CONSUMED_QUEUES, (
            f"task_routes sends {task_name} to queue {queue!r}, which no "
            f"worker consumes (consumed: {sorted(CONSUMED_QUEUES)})."
        )


def _decorator_queue_kwargs() -> list[tuple[str, int, str]]:
    """Static scan: ``(relative_path, lineno, queue)`` for every task
    decorator under ``echoroo/workers/`` that passes ``queue=<literal>``.

    Walks the AST rather than importing the modules so ``ml_tasks`` /
    ``model_preloader`` (TensorFlow) stay out of the unit-test process,
    and so a task nobody has imported yet is still covered. Both
    ``@shared_task(...)`` and ``@app.task(...)`` spellings are matched.
    """
    found: list[tuple[str, int, str]] = []
    for path in sorted(_WORKERS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for deco in node.decorator_list:
                if not isinstance(deco, ast.Call):
                    continue
                func = deco.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if name not in _TASK_DECORATORS:
                    continue
                for kw in deco.keywords:
                    if kw.arg == "queue" and isinstance(kw.value, ast.Constant):
                        found.append((path.name, kw.value.lineno, str(kw.value.value)))
    return found


def test_decorator_queue_kwargs_name_consumed_queues() -> None:
    """No task decorator under ``echoroo/workers/`` may name an orphan queue.

    This is the layer that would have caught both the outbox task and
    ``audit_log_export.export_weekly`` on the day they were written,
    regardless of whether beat or a ``.delay()`` call dispatches them.
    """
    offenders = [
        (file, line, queue)
        for file, line, queue in _decorator_queue_kwargs()
        if queue not in CONSUMED_QUEUES
    ]
    assert not offenders, (
        "task decorators name queues no worker consumes "
        f"(consumed: {sorted(CONSUMED_QUEUES)}): "
        + ", ".join(f"{f}:{ln} queue={q!r}" for f, ln, q in offenders)
        + ". Remember the compose *service* name (worker-cpu) is not a "
        "queue name. Drop the ``queue=`` argument so the task rides "
        "task_default_queue, or subscribe a worker to it in "
        "compose.dev.yaml and add it to CONSUMED_QUEUES."
    )


def test_decorator_scan_sees_the_workers_package() -> None:
    """Guard the scanner itself: it must actually find task decorators.

    If the package moved or the decorator spelling changed, the scan
    above would trivially pass on an empty list — this makes that
    failure loud instead.
    """
    task_defs = 0
    for path in _WORKERS_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for deco in node.decorator_list:
                    func = deco.func if isinstance(deco, ast.Call) else deco
                    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                    if name in _TASK_DECORATORS:
                        task_defs += 1
    assert task_defs >= len(app.conf.beat_schedule), (
        f"AST scan found only {task_defs} task decorators under "
        f"{_WORKERS_DIR} but beat_schedule has {len(app.conf.beat_schedule)} "
        "entries — the scanner is looking in the wrong place."
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
