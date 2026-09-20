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


def test_flags_boto3_client_s3_positional(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(tmp_path, "module.py", 'import boto3\nc = boto3.client("s3")\n')
    findings = lint.find_violations(tmp_path)
    assert len(findings) == 1
    assert "client('s3', ...)" in findings[0]
    assert ":2:" in findings[0]


def test_flags_service_name_keyword(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(tmp_path, "module.py", 'import boto3\nc = boto3.client(service_name="s3")\n')
    assert len(lint.find_violations(tmp_path)) == 1


def test_flags_resource_and_session_receiver(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(
        tmp_path,
        "module.py",
        'import boto3\nboto3.resource("s3")\nboto3.Session().client("s3")\n',
    )
    assert len(lint.find_violations(tmp_path)) == 2


def test_ignores_other_services(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(tmp_path, "module.py", 'import boto3\nboto3.client("kms")\n')
    assert lint.find_violations(tmp_path) == []


def test_flags_raw_client_accessor_import_and_use(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(
        tmp_path,
        "module.py",
        "from echoroo.core.s3 import get_s3_client\nc = get_s3_client()\n",
    )
    findings = lint.find_violations(tmp_path)
    assert len(findings) == 2
    assert ":1:" in findings[0] and "get_s3_client" in findings[0]
    assert ":2:" in findings[1] and "get_s3_client" in findings[1]


def test_flags_raw_client_accessor_attribute(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(
        tmp_path,
        "module.py",
        "from echoroo.core import s3\nc = s3.get_public_s3_client()\n",
    )
    findings = lint.find_violations(tmp_path)
    assert len(findings) == 1
    assert "get_public_s3_client" in findings[0]


def test_allows_helper_usage(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(
        tmp_path,
        "module.py",
        'from echoroo.core.s3 import put_object, delete_object\nput_object("k", b"x")\n',
    )
    assert lint.find_violations(tmp_path) == []


def test_core_s3_is_allowlisted(tmp_path: Path) -> None:
    lint = _load_lint()
    source = 'import boto3\nc = boto3.client("s3")\n'
    _write(tmp_path, "apps/api/echoroo/core/s3.py", source)
    assert lint.find_violations(tmp_path) == []

    _write(tmp_path, "apps/api/echoroo/core/other.py", source)
    assert len(lint.find_violations(tmp_path)) == 1


def test_syntax_error_raises_runtime_error(tmp_path: Path) -> None:
    lint = _load_lint()
    _write(tmp_path, "module.py", "def (:\n")
    with pytest.raises(RuntimeError):
        lint.find_violations(tmp_path)


def test_repository_is_clean() -> None:
    lint = _load_lint()
    source_root = None
    for parent in Path(__file__).resolve().parents:
        if (parent / "scripts" / "lint_s3_isolation.py").exists():
            source_root = parent
            break
    if source_root is None:
        pytest.skip("repository source root not found")

    api_root = source_root / "apps/api/echoroo"
    root = api_root if api_root.exists() else source_root / "echoroo"
    if not root.exists():
        pytest.skip("repository echoroo source root not found")
    findings = lint.find_violations(root)
    assert findings == [], "\n".join(findings)
