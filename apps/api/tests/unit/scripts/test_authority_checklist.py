"""Unit tests for the OSJ checklist converter and the authority loader CLI."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from echoroo.scripts.load_authority_checklist import _build_parser, read_checklist_csv


def _load_converter():  # type: ignore[no-untyped-def]
    """Import apps/api/scripts/convert_osj_checklist.py (not a package)."""
    override = os.environ.get("ECHOROO_CONVERT_OSJ_SCRIPT_PATH")
    candidates = [Path(override)] if override else []
    here = Path(__file__).resolve()
    candidates += [p / "scripts" / "convert_osj_checklist.py" for p in here.parents]
    candidates.append(Path("/tmp/convert_osj_checklist.py"))
    for candidate in candidates:
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location("convert_osj_checklist", candidate)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            sys.modules["convert_osj_checklist"] = module
            spec.loader.exec_module(module)
            return module
    pytest.skip("convert_osj_checklist.py not reachable from this checkout")


HEADER = ("掲載順", "Part", "カテゴリ", "種番号", "亜種番号", "学名", "著者", "和名")


def test_converter_keeps_species_rows_only_sorted_and_stripped() -> None:
    conv = _load_converter()
    rows = [
        HEADER,
        (1, "A", "目", None, None, "ANSERIFORMES", None, "カモ目"),
        (5, "A", "属", None, None, "BRANTA", "Scopoli", "コクガン属"),
        (6, "A", "種", 1, None, " Passer montanus ", "(Linnaeus, 1758)", " スズメ "),
        (7, "A", "亜種", 1, 1, "Passer montanus saturatus", None, "スズメ"),
        (8, "B", "種", 2, None, "Acridotheres cristatellus", None, "ハッカチョウ"),
        (9, "A", "種", 3, None, "Blankus name", None, ""),
    ]
    assert conv.extract_species_rows(rows) == [
        ("Acridotheres cristatellus", "ハッカチョウ"),
        ("Passer montanus", "スズメ"),
    ]


def test_converter_rejects_reordered_header() -> None:
    conv = _load_converter()
    with pytest.raises(ValueError, match="unexpected header"):
        conv.extract_species_rows([("学名", "和名"), ("Passer montanus", "スズメ")])


def test_converter_writes_deterministic_csv(tmp_path: Path) -> None:
    conv = _load_converter()
    out = tmp_path / "osj.csv"
    n = conv.write_csv([("Passer montanus", "スズメ"), ("Hirundo rustica", "ツバメ")], out)
    assert n == 2
    assert out.read_text(encoding="utf-8") == (
        "scientific_name,name\nPasser montanus,スズメ\nHirundo rustica,ツバメ\n"
    )


def test_loader_reads_csv_and_skips_blank_cells(tmp_path: Path) -> None:
    p = tmp_path / "in.csv"
    p.write_text("scientific_name,name\nPasser montanus, スズメ \n,\nX y,\n", encoding="utf-8")
    assert read_checklist_csv(p) == [("Passer montanus", "スズメ")]


def test_loader_rejects_csv_without_required_columns(tmp_path: Path) -> None:
    p = tmp_path / "bad.csv"
    p.write_text("species,japanese\nPasser montanus,スズメ\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required column"):
        read_checklist_csv(p)


def test_cli_requires_confirm() -> None:
    args = _build_parser().parse_args(["x.csv"])
    assert args.confirm is False
    assert args.locale == "ja"
