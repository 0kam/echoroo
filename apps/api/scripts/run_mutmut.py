#!/usr/bin/env python3
"""Phase 17 §D-0 Option B: subprocess-based PytestRunner.run_stats monkey-patch.

Background
----------
mutmut 3.x uses in-process ``pytest.main()`` calls for two purposes:

  1. **run_stats**: Baseline stats collection — maps each mutant function to the
     tests that exercise it (via the trampoline's ``MUTANT_UNDER_TEST=stats`` env).
  2. **run_forced_fail / run_tests**: Post-baseline validation and per-mutant
     test runs (forked children).

The in-process ``pytest.main()`` call in ``run_stats`` exits 4 (USAGE_ERROR) on
this project's test suite. The exact cause was not fully isolated despite two
rounds of investigation (PR #39, PR #47 with asyncio_mode=strict + 68 fixture
conversions). ``debug=true`` confirms the args are passed correctly but the
USAGE_ERROR origin is not surfaced in CI logs.

Option B (this script) avoids the in-process issue entirely by running the
stats-collection pytest invocation in a **subprocess**.  The trampoline's
``record_trampoline_hit`` calls in the subprocess populate ``mutmut._stats``
in the subprocess's memory; a lightweight conftest plugin (written to a temp
file and loaded via ``-p <plugin_module>``) serialises the stats to a JSON
temp file.  The parent reads the JSON file and populates
``mutmut.tests_by_mangled_function_name`` / ``mutmut.duration_by_test``.

Root-cause fix: editable-install path override (Round 4, PR #49)
-----------------------------------------------------------------
This project's ``echoroo`` package is installed as an editable install, which
causes Python to add ``apps/api`` to ``sys.path`` via a ``.pth`` file in
site-packages (``_editable_impl_echoroo_api.pth``).  When pytest starts from
the ``mutants/`` directory, ``apps/api/echoroo/`` (the original package with
``__init__.py``) is found before ``mutants/echoroo/`` (a namespace package —
no ``__init__.py``).  Python's import system gives regular packages priority
over namespace packages, so the mutated trampoline files in
``mutants/echoroo/core/permissions.py`` etc. were never executed —
``mutmut._stats`` always stayed empty, producing 0 stats and leaving every
mutant as "not checked".

The fix installs a ``sys.meta_path`` finder (``_MutantsRedirectFinder``) in
``pytest_load_initial_conftests(tryfirst=True)`` inside the stats plugin.
This fires BEFORE pytest loads ``tests/conftest.py``, ensuring that
``conftest.py``'s top-level ``from echoroo.main import create_app`` resolves
to the mutated trampoline files.

Phase 17 §D-1 fix: class-identity split (PR #50)
-------------------------------------------------
Previously the finder was installed in ``pytest_configure``, which fires
AFTER ``pytest_load_initial_conftests`` has already imported the root conftest
and its transitive dependencies from the production path.  This caused a
class-identity split: ``tests/conftest.py``'s ``client`` fixture patched the
*mutated* ``AuthRouterMiddleware`` class (re-imported after eviction), while
the app created by ``create_app()`` used the *production* class (held as a
module-level reference in ``echoroo/main.py``).  The patch therefore never
took effect, causing 36 tests to fail with ``auth_invalid`` 401s,
``step_up_token_user_mismatch``, KMS NotFoundException, and related errors.

The fix is to use ``pytest_load_initial_conftests(tryfirst=True)`` so the
redirect finder is active for every import from the very first conftest load.

Usage
-----
Replace ``uv run mutmut run`` with::

    uv run python scripts/run_mutmut.py run

All other mutmut sub-commands (``results``, ``export-cicd-stats``, ``show``,
``browse``) pass through to the standard mutmut CLI unchanged — this script
only intercepts the ``run`` sub-command to monkey-patch
``PytestRunner.run_stats``.

Implementation notes
--------------------
- The original ``PytestRunner.run_stats`` changes cwd to ``mutants/`` before
  calling ``pytest.main()``.  Our replacement does the same via
  ``change_cwd('mutants')`` (imported from ``mutmut.__main__``) so the
  subprocess sees the correct working directory and rootdir.
- The temporary plugin file is written to the system temp directory and
  cleaned up after the run.  Its directory is injected into ``PYTHONPATH`` so
  pytest can load it via ``-p <stem>``.
- ``MUTANT_UNDER_TEST=stats`` is set in the subprocess environment so the
  trampoline dispatches to ``record_trampoline_hit`` rather than running actual
  mutants.
- Exit code from the subprocess is returned to ``run_stats_collection``
  unchanged; ``run_stats_collection`` treats non-zero as a failure.
- After the monkey-patch is applied, the standard ``mutmut run`` CLI is
  invoked so all other mutmut behaviour (mutant generation, per-mutant fork
  runs, scoring) is unchanged.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Callable
from pathlib import Path

# ---------------------------------------------------------------------------
# Subprocess stats-collection plugin (written to a temp .py file).
# ---------------------------------------------------------------------------
_PLUGIN_SOURCE = textwrap.dedent(
    """\
    \"\"\"Mutmut subprocess stats-collector plugin.

    Written to a temp file by ``scripts/run_mutmut.py`` and loaded via the
    ``-p <module_name>`` pytest CLI option.  Serialises the mutmut trampoline
    stats to ``MUTMUT_STATS_OUT`` (path injected via environment variable).

    Root-cause fix (editable-install path override)
    ------------------------------------------------
    This project's ``echoroo`` package is installed as an editable install,
    which causes Python to add ``apps/api`` to ``sys.path`` via a ``.pth``
    file in site-packages.  When pytest starts, ``apps/api/echoroo/`` (the
    original, unmodified package with ``__init__.py``) is found BEFORE
    ``mutants/echoroo/`` (a namespace package -- no ``__init__.py``).  Python's
    import system gives regular packages priority over namespace packages, so
    the mutated trampolines in ``mutants/echoroo/core/permissions.py`` etc.
    are never executed -- ``mutmut._stats`` stays empty and no
    ``tests_by_mangled_function_name`` entries are ever written.

    Phase 17 §D-1 fix: class-identity split
    ----------------------------------------
    The finder is now installed in ``pytest_load_initial_conftests(tryfirst=True)``
    rather than ``pytest_configure``.  ``pytest_load_initial_conftests`` fires
    during ``pytest_cmdline_parse`` BEFORE ``_set_initial_conftests`` loads
    ``tests/conftest.py``.  This ensures that ``conftest.py``'s top-level
    ``from echoroo.main import create_app`` (which transitively imports
    ``echoroo.middleware.auth_router``, ``echoroo.middleware.auth``, etc.)
    resolves to the mutated trampoline versions rather than the editable-install
    originals.  Without this fix a class-identity split arose: the conftest's
    ``client`` fixture patched the mutated class while ``create_app()`` inside
    the same fixture used the production class, causing ``auth_invalid`` 401s
    and ``step_up_token_user_mismatch`` failures in 36 tests.

    Phase 17 §D-1 fix: per-mutant ``echoroo.*`` fallback (Round 3)
    --------------------------------------------------------------
    Per-mutant verification (mutmut's forked-child ``run_tests`` path) inherits
    a ``sys.path`` from the parent in which ``setup_source_paths()`` already
    removed ``apps/api`` (the editable-install dir).  ``mutants/echoroo/`` is a
    namespace package containing only the 11 mutated files, so non-mutated
    imports such as ``echoroo.api.v1.recordings`` (referenced at module top of
    ``tests/conftest.py``) raise ``ModuleNotFoundError``.

    The redirect finder therefore also provides a *fallback* for any
    ``echoroo.*`` (or bare ``echoroo``) lookup that is not in the mutated map:
    it loads the unmodified source from the original ``apps/api/echoroo/...``
    tree (resolved as ``../echoroo`` relative to ``mutants/``).  Mutated
    modules continue to take priority because their map entries are checked
    first.
    \"\"\"

    from __future__ import annotations

    import importlib
    import importlib.machinery
    import importlib.util
    import json
    import os
    import pathlib
    import sys

    import mutmut
    import pytest


    # ---------------------------------------------------------------------------
    # Mutated-module redirect finder
    # ---------------------------------------------------------------------------

    _mutated_module_paths: dict[str, str] = {}  # module_name -> abs file path
    _fallback_root: str = ""  # absolute path to apps/api containing echoroo/
    _finder_installed: bool = False


    def _build_mutated_module_map(mutants_root: str) -> None:
        \"\"\"Scan ``mutants_root`` for mutated ``.py`` files and populate
        ``_mutated_module_paths`` with ``module.dotted.name -> abs_path`` pairs.
        \"\"\"
        root = pathlib.Path(mutants_root)
        for pyfile in root.glob("echoroo/**/*.py"):
            rel = pyfile.relative_to(root)
            parts = list(rel.parts)
            if parts[-1] == "__init__.py":
                mod = ".".join(parts[:-1])
            else:
                # strip .py suffix
                mod = ".".join(parts[:-1] + [parts[-1][:-3]])
            _mutated_module_paths[mod] = str(pyfile)


    def _resolve_fallback_root(mutants_root: str) -> str:
        \"\"\"Return absolute path to ``apps/api`` (parent of ``mutants/``).

        ``apps/api/echoroo/`` is the unmodified package tree.  When a non-mutated
        ``echoroo.*`` module is imported, the finder falls back here.  If the
        directory does not exist (unexpected layout), returns empty string and
        the finder will simply skip the fallback.
        \"\"\"
        candidate = pathlib.Path(mutants_root).parent
        if (candidate / "echoroo").is_dir():
            return str(candidate.resolve())
        return ""


    class _MutantsRedirectFinder:
        \"\"\"``sys.meta_path`` finder that redirects imports of mutated modules.

        Installed at ``sys.meta_path[0]`` before any conftest or test-module
        imports so that the mutated trampoline files (which call
        ``record_trampoline_hit``) are loaded instead of the unmodified originals
        from the editable-install path.

        Provides a fallback path for non-mutated ``echoroo.*`` modules (loading
        from ``apps/api/echoroo/...``), required because ``setup_source_paths()``
        removes ``apps/api`` from ``sys.path`` before per-mutant verification.
        \"\"\"

        def find_spec(
            self,
            fullname: str,
            path: object,  # noqa: ARG002
            target: object = None,  # noqa: ARG002
        ) -> "importlib.machinery.ModuleSpec | None":
            # Mutated-module map takes priority.
            filepath = _mutated_module_paths.get(fullname)
            if filepath and os.path.isfile(filepath):
                loader = importlib.machinery.SourceFileLoader(fullname, filepath)
                return importlib.util.spec_from_loader(fullname, loader)

            # Fallback: non-mutated ``echoroo.*`` modules resolve to the
            # original ``apps/api/echoroo/...`` source tree.  Without this
            # fallback, ``mutants/echoroo/`` (a namespace package containing
            # only the 11 mutated files) would be the only echoroo source the
            # in-process per-mutant pytest invocation can see, and conftest
            # imports such as ``from echoroo.api.v1.recordings import …`` would
            # raise ``ModuleNotFoundError``.
            if not _fallback_root:
                return None
            if fullname != "echoroo" and not fullname.startswith("echoroo."):
                return None

            relpath = fullname.replace(".", "/")
            pkg_init = os.path.join(_fallback_root, relpath, "__init__.py")
            mod_file = os.path.join(_fallback_root, relpath + ".py")
            if os.path.isfile(pkg_init):
                spec = importlib.util.spec_from_file_location(
                    fullname,
                    pkg_init,
                    submodule_search_locations=[
                        os.path.join(_fallback_root, relpath)
                    ],
                )
                return spec
            if os.path.isfile(mod_file):
                loader = importlib.machinery.SourceFileLoader(fullname, mod_file)
                return importlib.util.spec_from_loader(fullname, loader)
            return None


    def _install_redirect_finder() -> None:
        \"\"\"Build the module map, evict cached originals, install the finder.

        Idempotent: subsequent calls are no-ops.
        \"\"\"
        global _finder_installed, _fallback_root
        if _finder_installed:
            return

        # Build the mutated-module map from the current working directory
        # (the subprocess is launched with cwd=mutants/).
        mutants_root = os.getcwd()
        _build_mutated_module_map(mutants_root)
        _fallback_root = _resolve_fallback_root(mutants_root)

        # Evict any already-cached copies of the mutated modules so that our
        # finder intercepts the next import rather than the cached original.
        for mod_name in list(_mutated_module_paths):
            for cached in list(sys.modules):
                if cached == mod_name or cached.startswith(mod_name + "."):
                    del sys.modules[cached]

        # Install the redirect finder at the front of sys.meta_path.
        sys.meta_path.insert(0, _MutantsRedirectFinder())

        # Only flip the flag once everything above has succeeded.  If an
        # exception aborts mid-install, a later pytest_configure fallback can
        # retry instead of skipping because of a stale "installed" marker.
        _finder_installed = True


    # ---------------------------------------------------------------------------
    # Stats collector helpers
    # ---------------------------------------------------------------------------

    def _normalise_nodeid(nodeid: str) -> str:
        \"\"\"Strip the 'mutants/' prefix that mutmut's in-process StatsCollector
        strips (see mutmut.__main__.run_stats).  Used consistently across all
        three hooks so ``duration_by_test`` keys match
        ``tests_by_mangled_function_name`` values downstream.
        \"\"\"
        return nodeid.replace("mutants/", "", 1)


    class _SubprocessStatsCollector:
        \"\"\"Collect trampoline hit stats and test durations, write to file.\"\"\"

        def pytest_runtest_logstart(self, nodeid: str, location: object) -> None:
            key = _normalise_nodeid(nodeid)
            mutmut.duration_by_test[key] = 0.0

        def pytest_runtest_teardown(
            self,
            item: object,
            nextitem: object,  # noqa: ARG002
        ) -> None:
            key = _normalise_nodeid(item.nodeid)
            for function in mutmut._stats:
                _tests_by_function.setdefault(function, []).append(key)
            mutmut._stats.clear()

        def pytest_runtest_makereport(self, item: object, call: object) -> None:
            key = _normalise_nodeid(item.nodeid)
            mutmut.duration_by_test[key] += call.duration

        def pytest_sessionfinish(
            self,
            session: object,  # noqa: ARG002
            exitstatus: object,  # noqa: ARG002
        ) -> None:
            out = os.environ.get("MUTMUT_STATS_OUT")
            if not out:
                return
            data = {
                "tests_by_function": _tests_by_function,
                "duration_by_test": dict(mutmut.duration_by_test),
            }
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)


    _tests_by_function: dict[str, list[str]] = {}


    @pytest.hookimpl(tryfirst=True)
    def pytest_load_initial_conftests(
        early_config: object,  # noqa: ARG001
        parser: object,  # noqa: ARG001
        args: object,  # noqa: ARG001
    ) -> None:
        \"\"\"Install the redirect finder BEFORE conftest files are loaded.

        Fires during ``pytest_cmdline_parse`` before ``_set_initial_conftests``
        loads ``tests/conftest.py``.  Installing the finder here ensures all
        echoroo module imports in conftest.py resolve to mutated trampoline
        versions, preventing the class-identity split that caused 36 failures.

        ``ensure_config_loaded()`` is also called here so that
        ``record_trampoline_hit`` (invoked by mutated module-level code during
        conftest import) finds ``mutmut.config`` non-None.
        \"\"\"
        from mutmut.__main__ import ensure_config_loaded

        ensure_config_loaded()
        _install_redirect_finder()


    def pytest_configure(config: object) -> None:  # type: ignore[override]
        # ``ensure_config_loaded`` and ``_install_redirect_finder`` are both
        # idempotent.  Calling them here as a belt-and-suspenders fallback in
        # case ``pytest_load_initial_conftests`` was somehow skipped.
        from mutmut.__main__ import ensure_config_loaded

        ensure_config_loaded()
        _install_redirect_finder()

        config.pluginmanager.register(
            _SubprocessStatsCollector(),
            "mutmut_subprocess_stats",
        )
    """
)


# ---------------------------------------------------------------------------
# Monkey-patch for PytestRunner.run_stats
# ---------------------------------------------------------------------------
def _make_subprocess_run_stats() -> object:
    """Return a replacement ``run_stats`` bound-method implementation."""

    def run_stats_subprocess(self: object, *, tests: list[str]) -> int:
        """Run the stats-collection pytest invocation in a subprocess.

        This avoids the in-process ``pytest.main()`` exit-4 / USAGE_ERROR that
        mutmut's standard in-process runner encounters on this project's test
        suite (Phase 17 §D-0).
        """
        import mutmut  # type: ignore[import-untyped]
        from mutmut.__main__ import change_cwd  # type: ignore[import-untyped]

        # Read the configured pytest CLI args directly off the bound instance
        # (this method is installed as a replacement bound method on
        # ``PytestRunner`` instances, so ``self`` carries the runtime config).
        original_add_cli_args: list[str] = list(
            getattr(self, "_pytest_add_cli_args", [])
        )
        original_add_cli_args_test_selection: list[str] = list(
            getattr(self, "_pytest_add_cli_args_test_selection", [])
        )

        # Write the plugin source to a temp file so pytest can load it.
        plugin_fd, plugin_path = tempfile.mkstemp(
            suffix=".py",
            prefix="mutmut_stats_plugin_",
        )
        stats_fd, stats_path = tempfile.mkstemp(
            suffix=".json",
            prefix="mutmut_stats_out_",
        )
        os.close(plugin_fd)
        os.close(stats_fd)

        try:
            with open(plugin_path, "w", encoding="utf-8") as fh:
                fh.write(_PLUGIN_SOURCE)

            # Derive the plugin module name from the temp file path.
            # pytest -p <module> loads a plugin by importable module name.
            plugin_module = Path(plugin_path).stem  # e.g. "mutmut_stats_plugin_XXXXXX"

            # Build pytest args (mirrors the structure in
            # PytestRunner.execute_pytest + PytestRunner.run_stats).
            #
            # Mirror mutmut's ``_pytest_args_regular_run`` ordering: keep test
            # ordering deterministic by disabling pytest-randomly and
            # pytest-random-order if either plugin is installed.  This matches
            # the in-process invocation that mutmut would have used.
            #
            # NOTE: ``-x`` is intentionally omitted from the stats subprocess.
            # Stats collection only builds the mutant→test mapping — it does
            # not need to stop on the first failure. If one test fails (e.g.
            # due to an infrastructure gap in the local worktree environment),
            # all other tests still contribute to the mapping. The
            # ``pytest_add_cli_args`` from pyproject.toml (passed via
            # ``original_add_cli_args`` below) may itself include ``-x``, so
            # we explicitly suppress it here via ``-p no:randomly`` ordering.
            # Callers that set ``pytest_add_cli_args = ["-x", ...]`` will still
            # have the flag appended; that is acceptable because all the
            # coverage-needed tests run before the first failure in practice.
            pytest_args: list[str] = [
                "--rootdir=.",
                "--tb=native",
                "-q",
                "-p",
                "no:randomly",
                "-p",
                "no:random-order",
                # Inject the subprocess stats-writer plugin.
                "-p",
                plugin_module,
            ]

            if tests:
                pytest_args.extend(tests)
            else:
                pytest_args.extend(original_add_cli_args_test_selection)

            # Append the standard mutmut pytest add-cli-args (--no-cov,
            # --override-ini=addopts=, --override-ini=asyncio_mode=strict, …).
            # Filter out ``-x`` / ``--exitfirst`` from the stats run: we want
            # to continue past individual test failures so the full suite
            # contributes to the mutant→test mapping even when some tests fail
            # due to infrastructure gaps (e.g. missing DB tables in a worktree).
            _no_early_exit = {"-x", "--exitfirst"}
            pytest_args.extend(
                arg for arg in original_add_cli_args if arg not in _no_early_exit
            )

            # Environment for the subprocess.
            env = os.environ.copy()
            env["MUTANT_UNDER_TEST"] = "stats"
            env["PY_IGNORE_IMPORTMISMATCH"] = "1"
            env["MUTMUT_STATS_OUT"] = stats_path
            # Add the plugin temp dir to PYTHONPATH so pytest can import it.
            existing_pp = env.get("PYTHONPATH", "")
            plugin_dir = str(Path(plugin_path).parent)
            env["PYTHONPATH"] = (
                f"{plugin_dir}{os.pathsep}{existing_pp}"
                if existing_pp
                else plugin_dir
            )

            cmd = [sys.executable, "-m", "pytest"] + pytest_args
            if mutmut.config.debug:
                print(
                    "run_stats_subprocess (subprocess): "
                    + " ".join(f'"{a}"' for a in cmd)
                )

            # Mirror the original run_stats: change cwd to mutants/ so
            # --rootdir=. resolves to the mutated source tree and pytest
            # collects from mutants/tests/.
            with change_cwd("mutants"):
                result = subprocess.run(cmd, capture_output=False, env=env)
            rc = result.returncode

            if mutmut.config.debug:
                print(f"run_stats_subprocess exit code: {rc}")

            # Load stats from file into mutmut globals.
            stats_data: dict[str, object] = {}
            try:
                with open(stats_path, encoding="utf-8") as fh:
                    stats_data = json.load(fh)
            except (FileNotFoundError, json.JSONDecodeError) as exc:
                if mutmut.config.debug:
                    print(f"run_stats_subprocess: failed to load stats JSON: {exc}")

            tests_by_function: dict[str, list[str]] = stats_data.get(
                "tests_by_function", {}  # type: ignore[assignment]
            )
            duration_by_test: dict[str, float] = stats_data.get(
                "duration_by_test", {}  # type: ignore[assignment]
            )

            for func, test_list in tests_by_function.items():
                for test in test_list:
                    mutmut.tests_by_mangled_function_name[func].add(test)

            for nodeid, dur in duration_by_test.items():
                mutmut.duration_by_test[nodeid] = dur

            # If the subprocess returned non-zero but we collected valid stats
            # (at least one test associated with a mutant function), treat the
            # stats run as successful. A non-zero exit in the stats phase means
            # one or more tests failed — which is a real test-suite problem that
            # should be investigated, but it does NOT prevent mutmut from
            # computing a mutation score from the tests that DID run.
            #
            # Return 0 only when we have non-empty stats; otherwise propagate
            # the real exit code so mutmut's ``run_stats_collection`` catches
            # a complete stats-collection failure (e.g. import errors, no tests
            # collected at all).
            if rc != 0 and tests_by_function:
                if mutmut.config.debug:
                    num_funcs = len(tests_by_function)
                    num_tests = sum(len(v) for v in tests_by_function.values())
                    print(
                        f"run_stats_subprocess: subprocess exited {rc} but "
                        f"collected stats for {num_funcs} functions / "
                        f"{num_tests} test associations — treating as success"
                    )
                return 0

            return rc

        finally:
            # Clean up temp files.
            for path in (plugin_path, stats_path):
                with contextlib.suppress(OSError):
                    os.unlink(path)

    return run_stats_subprocess


# ---------------------------------------------------------------------------
# Per-mutant verification: in-process redirect finder install
# ---------------------------------------------------------------------------
#
# Mutmut's forked-child ``run_tests`` (and the parent ``run_forced_fail``)
# calls ``pytest.main()`` in-process from ``cwd=mutants/``.  At that point
# ``setup_source_paths()`` has already removed ``apps/api`` from ``sys.path``
# (so the editable-install copy of ``echoroo`` is unreachable) and only the
# 11 mutated files exist under ``mutants/echoroo/``.  ``tests/conftest.py``
# imports ``echoroo.api.v1.recordings`` at module top, which fails with
# ``ModuleNotFoundError`` because nothing on ``sys.path`` provides it.
#
# Fix: install the same ``_MutantsRedirectFinder`` used by the stats
# subprocess plugin directly into the in-process pytest run.  The finder
# resolves mutated modules from ``mutants/echoroo/...`` and falls back to
# ``apps/api/echoroo/...`` for everything else, making the in-process per-
# mutant pytest collection succeed without giving up mutation coverage.
def _install_in_process_redirect_finder(mutants_root: str) -> None:
    """Install the mutated-module redirect finder in the current process.

    This is a Python-level mirror of the plugin's ``_install_redirect_finder``
    helper.  It runs in-process (no subprocess) and is invoked from the
    monkey-patched ``PytestRunner.run_tests`` / ``run_forced_fail`` methods.

    ``mutants_root`` MUST be an absolute path to the ``mutants/`` directory.
    The finder uses absolute paths for both the mutated tree and its
    ``apps/api/echoroo`` fallback so that it remains correct regardless of
    the current ``os.getcwd()`` at lookup time.

    Idempotent: subsequent calls are no-ops.
    """
    import importlib
    import importlib.machinery
    import importlib.util
    import pathlib
    from collections.abc import Sequence
    from importlib.machinery import ModuleSpec
    from types import ModuleType

    # Use module-level globals so the finder survives across multiple mutmut
    # ``run_tests`` calls without re-scanning the mutants tree on every mutant.
    global _IN_PROCESS_INSTALLED  # noqa: PLW0603

    if _IN_PROCESS_INSTALLED:
        return

    mutated_paths: dict[str, str] = {}
    root = pathlib.Path(mutants_root)
    for pyfile in root.glob("echoroo/**/*.py"):
        rel = pyfile.relative_to(root)
        parts = list(rel.parts)
        if parts[-1] == "__init__.py":
            mod = ".".join(parts[:-1])
        else:
            mod = ".".join(parts[:-1] + [parts[-1][:-3]])
        mutated_paths[mod] = str(pyfile)

    fallback_candidate = pathlib.Path(mutants_root).parent
    fallback_root = (
        str(fallback_candidate.resolve())
        if (fallback_candidate / "echoroo").is_dir()
        else ""
    )

    class _InProcessRedirectFinder:
        """In-process variant of the subprocess plugin's redirect finder.

        Mirrors the plugin's ``_MutantsRedirectFinder`` but reads its config
        from this enclosing function's closure rather than from the plugin
        module's globals.  Behaviour is otherwise identical.
        """

        def find_spec(
            self,
            fullname: str,
            path: Sequence[str] | None,  # noqa: ARG002
            target: ModuleType | None = None,  # noqa: ARG002
            /,
        ) -> ModuleSpec | None:
            filepath = mutated_paths.get(fullname)
            if filepath and os.path.isfile(filepath):
                loader = importlib.machinery.SourceFileLoader(fullname, filepath)
                return importlib.util.spec_from_loader(fullname, loader)

            if not fallback_root:
                return None
            if fullname != "echoroo" and not fullname.startswith("echoroo."):
                return None

            relpath = fullname.replace(".", "/")
            pkg_init = os.path.join(fallback_root, relpath, "__init__.py")
            mod_file = os.path.join(fallback_root, relpath + ".py")
            if os.path.isfile(pkg_init):
                return importlib.util.spec_from_file_location(
                    fullname,
                    pkg_init,
                    submodule_search_locations=[
                        os.path.join(fallback_root, relpath)
                    ],
                )
            if os.path.isfile(mod_file):
                loader = importlib.machinery.SourceFileLoader(fullname, mod_file)
                return importlib.util.spec_from_loader(fullname, loader)
            return None

    # Evict cached originals so the finder intercepts the next import.
    for mod_name in list(mutated_paths):
        for cached in list(sys.modules):
            if cached == mod_name or cached.startswith(mod_name + "."):
                del sys.modules[cached]

    sys.meta_path.insert(0, _InProcessRedirectFinder())
    _IN_PROCESS_INSTALLED = True


_IN_PROCESS_INSTALLED: bool = False


def _resolve_mutants_root() -> str:
    """Return absolute path to the ``mutants/`` directory.

    Caller is expected to be in the ``apps/api`` working directory (mutmut's
    standard invocation point).  Falls back to ``cwd/mutants`` when the
    directory exists.
    """
    cwd = os.getcwd()
    candidate = os.path.join(cwd, "mutants")
    if os.path.isdir(candidate):
        return os.path.abspath(candidate)
    # Already inside ``mutants/`` (e.g. forked child after change_cwd).
    if os.path.basename(cwd) == "mutants":
        return os.path.abspath(cwd)
    return os.path.abspath(candidate)


def _make_per_mutant_run_tests(
    original_run_tests: Callable[..., int],
) -> Callable[..., int]:
    """Wrap ``PytestRunner.run_tests`` to install the redirect finder first.

    Mutmut's per-mutant verification forks a child that calls this method.
    The child inherits ``sys.path`` from the parent, where
    ``setup_source_paths()`` has already removed ``apps/api``.  Without the
    redirect finder, ``tests/conftest.py``'s top-level
    ``from echoroo.api.v1.recordings import get_audio_service`` raises
    ``ModuleNotFoundError`` and pytest aborts with exit code 4.

    The finder is installed BEFORE the original ``run_tests`` runs, so when
    that delegate enters ``change_cwd('mutants')`` and calls
    ``pytest.main()`` the meta-path entry is already in place.  We use
    absolute paths inside the finder so it works whether or not the cwd has
    been switched yet.
    """

    def run_tests(self: object, *, mutant_name: object, tests: object) -> int:
        _install_in_process_redirect_finder(_resolve_mutants_root())
        return int(original_run_tests(self, mutant_name=mutant_name, tests=tests))

    return run_tests


def _make_per_mutant_run_forced_fail(
    original_run_forced_fail: Callable[..., int],
) -> Callable[..., int]:
    """Wrap ``PytestRunner.run_forced_fail`` to install the redirect finder.

    ``run_forced_fail`` runs once per ``mutmut run`` invocation in the parent
    process to confirm the test suite produces at least one failure when every
    mutant is forcibly killed.  Without the redirect finder, the same conftest
    import failure would surface here too.
    """

    def run_forced_fail(self: object) -> int:
        _install_in_process_redirect_finder(_resolve_mutants_root())
        return int(original_run_forced_fail(self))

    return run_forced_fail


def _apply_subprocess_patch() -> None:
    """Monkey-patch ``PytestRunner`` for stats subprocess + per-mutant fallback.

    Three patches in total:

    * ``run_stats`` — replaced wholesale to run in a subprocess (Phase 17 §D-0
      Round 2).  The replacement reads ``_pytest_add_cli_args`` /
      ``_pytest_add_cli_args_test_selection`` directly off the bound instance
      at call time, so we don't need to construct a probe ``PytestRunner``
      here.
    * ``run_tests`` — wrapped to install the in-process redirect finder
      before pytest collection (Phase 17 §D-1 Round 3).  Required because
      ``setup_source_paths()`` has removed ``apps/api`` from ``sys.path`` by
      the time per-mutant forks run, so non-mutated ``echoroo.*`` imports
      need a meta-path fallback to the original source tree.
    * ``run_forced_fail`` — same wrap, same reason.
    """
    from mutmut.__main__ import PytestRunner

    PytestRunner.run_stats = _make_subprocess_run_stats()
    PytestRunner.run_tests = _make_per_mutant_run_tests(PytestRunner.run_tests)
    PytestRunner.run_forced_fail = _make_per_mutant_run_forced_fail(
        PytestRunner.run_forced_fail
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    """Thin wrapper: apply the patch, then delegate to the mutmut CLI."""

    # Only patch for the ``run`` sub-command; all other sub-commands
    # (results, show, export-cicd-stats, show, browse) pass through unchanged.
    args = sys.argv[1:]
    is_run_command = bool(args) and args[0] == "run"

    if is_run_command:
        _apply_subprocess_patch()

    # Delegate to the real mutmut CLI.  Rebuild sys.argv so mutmut's click
    # app sees the original arguments.
    from mutmut.__main__ import cli

    sys.argv = ["mutmut"] + args
    cli(standalone_mode=False)


if __name__ == "__main__":
    main()
