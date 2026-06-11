"""In-process Alembic ``upgrade head`` helper for integration/security fixtures.

W0 mutation-harness fix #4 (decisive): the previous ``upgraded_db`` fixtures
shelled out to ``uv run alembic -c <ini> upgrade head`` via ``subprocess.run``.
That works in a normal pytest run, but it is the *root* of the recurring mutmut
``BASELINE FAILED`` whack-a-mole:

* mutmut copies the project into ``apps/api/mutants/`` and runs its full-suite
  ``run_stats`` from ``cwd=mutants/`` against a freshly built ``mutants/.venv``.
* ``uv run alembic`` resolves ``uv`` to the *nearest* venv — i.e.
  ``mutants/.venv`` — which does **not** carry the editable ``echoroo`` install,
  so the alembic subprocess dies importing ``alembic/env.py`` line 11
  (``from echoroo.core.settings import get_settings``).
* Earlier fixes peeled adjacent layers (copy README.md / alembic.ini /
  alembic/), but the copied-venv subprocess fragility kept resurfacing.

Running the upgrade **in-process** removes the subprocess (and the
``mutants/.venv`` dependency) entirely: the upgrade executes in the same
interpreter that already has ``echoroo`` importable, so ``env.py`` line 11
always resolves. It is also faster and less flaky in normal runs.

The only subtlety is locating the *real* ``alembic/`` source directory. Under
mutmut, ``__file__`` lives in ``mutants/tests/`` so deriving the alembic dir
from ``__file__`` would (correctly, since fix #3 copies it) point at
``mutants/alembic/`` — but to be robust against future harness changes we honour
the ``ECHOROO_ALEMBIC_DIR`` env var when set (the CI mutation step exports the
real absolute ``$GITHUB_WORKSPACE/apps/api/alembic``); otherwise we fall back to
the ``apps/api/alembic`` directory resolved relative to this file.
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic.config import Config

from alembic import command

# ``apps/api`` is two parents up from ``apps/api/tests/_alembic_upgrade.py``.
_API_ROOT = Path(__file__).resolve().parents[1]


def _resolve_alembic_dir() -> Path:
    """Return the absolute path to the real ``alembic/`` source directory.

    Honours ``ECHOROO_ALEMBIC_DIR`` (exported by the CI mutation step so the
    in-process upgrade targets real source rather than the ``mutants/`` copy);
    otherwise derives ``apps/api/alembic`` from this file's location.
    """
    override = os.environ.get("ECHOROO_ALEMBIC_DIR")
    if override:
        return Path(override).resolve()
    return _API_ROOT / "alembic"


def upgrade_head_in_process(
    *,
    async_url: str,
    sync_url: str,
    extra_env: dict[str, str] | None = None,
) -> None:
    """Run ``alembic upgrade head`` in-process against ``async_url``.

    Args:
        async_url: ``postgresql+asyncpg://...`` URL of the throwaway test
            database. ``alembic/env.py`` runs migrations in *online* (async)
            mode, so this is what the migration engine connects with.
        sync_url: ``postgresql://...`` URL (psycopg/sync) — surfaced to env.py
            via ``ALEMBIC_SYNC_URL`` for parity with the former subprocess
            environment; migrations that introspect that variable keep working.
        extra_env: Additional environment variables the migration env requires
            (e.g. ``JWT_SECRET_KEY``) for ``get_settings()`` validation.

    ``alembic/env.py`` overrides ``sqlalchemy.url`` from
    ``get_settings().DATABASE_URL``; ``get_settings`` is ``lru_cache``-d, so we
    set ``DATABASE_URL`` in ``os.environ`` and clear the cache *before*
    importing/running the env so it picks up the throwaway DB. Both the env
    mutations and the settings cache are restored afterwards to avoid leaking
    the testcontainer URL into the rest of the session.
    """
    from echoroo.core.settings import get_settings

    env_overrides: dict[str, str] = {
        "DATABASE_URL": async_url,
        "ALEMBIC_SYNC_URL": sync_url,
        **(extra_env or {}),
    }

    saved: dict[str, str | None] = {
        key: os.environ.get(key) for key in env_overrides
    }
    os.environ.update(env_overrides)
    get_settings.cache_clear()
    try:
        cfg = Config()
        cfg.set_main_option("script_location", str(_resolve_alembic_dir()))
        # env.py re-derives sqlalchemy.url from settings, but set it here too so
        # the config is internally consistent (and offline mode would work).
        cfg.set_main_option("sqlalchemy.url", async_url)
        command.upgrade(cfg, "head")
    finally:
        # Restore os.environ exactly (delete keys that were previously unset).
        for key, previous in saved.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
        # Drop the throwaway-DB settings so subsequent get_settings() calls
        # rebuild from the restored (real) environment.
        get_settings.cache_clear()
