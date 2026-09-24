"""Unit tests for scripts/lint_s3_isolation.py (storage migration slice 1)."""

from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path
from types import ModuleType

import pytest


def _load_lint() -> ModuleType:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "scripts" / "lint_s3_isolation.py"
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("lint_s3_isolation", candidate)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    pytest.skip("scripts/lint_s3_isolation.py not found in any ancestor directory")


def _write(root: Path, rel: str, source: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def _sdk_name() -> str:
    """Return the SDK package name used by the generated snippets."""
    return "boto" + "3"


def _sdk_subpackage_name() -> str:
    """Return the SDK subpackage name used by the generated snippets."""
    return "boto" + "core"


def test_flags_sdk_client_s3_positional(tmp_path: Path) -> None:
    lint = _load_lint()
    sdk = _sdk_name()
    _write(tmp_path, "module.py", f'c = {sdk}.client("s3")\n')
    findings = lint.find_violations(tmp_path)
    assert len(findings) == 1
    assert "client('s3', ...)" in findings[0]
    assert ":1:" in findings[0]


def test_flags_service_name_keyword(tmp_path: Path) -> None:
    lint = _load_lint()
    sdk = _sdk_name()
    _write(tmp_path, "module.py", f'c = {sdk}.client(service_name="s3")\n')
    assert len(lint.find_violations(tmp_path)) == 1


def test_flags_resource_and_session_receiver(tmp_path: Path) -> None:
    lint = _load_lint()
    sdk = _sdk_name()
    _write(
        tmp_path,
        "module.py",
        f'{sdk}.resource("s3")\n{sdk}.Session().client("s3")\n',
    )
    assert len(lint.find_violations(tmp_path)) == 2


def test_ignores_other_services(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(tmp_path, "module.py", f'{_sdk_name()}.client("kms")\n')
    assert lint.find_violations(tmp_path) == []


def test_flags_legacy_s3_import_and_use(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(
        tmp_path,
        "module.py",
        "from echoroo.core.s3 import get_s3_client\nc = get_s3_client()\n",
    )
    findings = lint.find_violations(tmp_path)
    assert len(findings) == 2
    assert ":1:" in findings[0] and "legacy S3 import" in findings[0]
    assert ":2:" in findings[1] and "get_s3_client" in findings[1]


def test_flags_raw_client_accessor_attribute(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(
        tmp_path,
        "module.py",
        "from echoroo.core import s3\nc = s3.get_s3_client()\n",
    )
    findings = lint.find_violations(tmp_path)
    assert len(findings) == 2
    assert "legacy S3 import" in findings[0]
    assert "get_s3_client" in findings[1]


def test_flags_any_legacy_s3_helper_import(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(
        tmp_path,
        "module.py",
        'from echoroo.core.s3 import put_object, delete_object\nput_object("k", b"x")\n',
    )
    findings = lint.find_violations(tmp_path)
    assert len(findings) == 1
    assert "legacy S3 import" in findings[0]


def test_core_s3_is_not_allowlisted(tmp_path: Path) -> None:
    lint = _load_lint()
    sdk = _sdk_name()
    source = f'import {sdk}\nc = {sdk}.client("s3")\n'
    _write(tmp_path, "apps/api/echoroo/core/s3.py", source)
    assert len(lint.find_violations(tmp_path)) == 2

    _write(tmp_path, "apps/api/echoroo/core/other.py", source)
    # import line + client construction
    assert len(lint.find_violations(tmp_path)) == 4


def test_flags_from_core_import_of_legacy_s3_module(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(tmp_path, "module.py", "from echoroo.core import s3\n")
    findings = lint.find_violations(tmp_path)
    assert len(findings) == 1
    assert "legacy S3 import" in findings[0]


def test_syntax_error_raises_runtime_error(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(tmp_path, "module.py", "def (:\n")
    with pytest.raises(RuntimeError):
        lint.find_violations(tmp_path)


def test_flags_sdk_import_forms(tmp_path: Path) -> None:
    lint = _load_lint()
    sdk = _sdk_name()
    sdk_subpackage = _sdk_subpackage_name()
    _write(
        tmp_path,
        "mod.py",
        f"""\
        from {sdk} import client as make
        import {sdk_subpackage}.exceptions
        c = make("s3")
        """,
    )
    findings = lint.find_violations(tmp_path)
    assert len(findings) == 2, findings
    assert ":1:" in findings[0] and _sdk_name() in findings[0]
    assert ":2:" in findings[1] and f"{_sdk_subpackage_name()}.exceptions" in findings[1]


def test_core_kms_has_no_sdk_import_exemption(tmp_path: Path) -> None:
    lint = _load_lint()
    sdk = _sdk_name()
    _write(
        tmp_path,
        "apps/api/echoroo/core/kms.py",
        f'import {sdk}\nk = {sdk}.client("kms")\n',
    )
    assert len(lint.find_violations(tmp_path)) == 1
    _write(
        tmp_path,
        "apps/api/echoroo/core/kms.py",
        f'import {sdk}\nk = {sdk}.client("s3")\n',
    )
    assert len(lint.find_violations(tmp_path)) == 2


def test_missing_scan_root_raises(tmp_path: Path) -> None:
    lint = _load_lint()
    with pytest.raises(RuntimeError):
        lint.find_violations(tmp_path / "does-not-exist")


def test_flags_sdk_module_reexported_through_wrapper(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(tmp_path, "mod.py", f"from echoroo.core.kms import {_sdk_name()}\n")
    findings = lint.find_violations(tmp_path)
    assert len(findings) == 1, findings
    assert _sdk_name() in findings[0]
