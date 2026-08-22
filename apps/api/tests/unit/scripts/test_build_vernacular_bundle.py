"""Unit tests for ``scripts/build_vernacular_bundle.py`` (WS-A v2 slice 2a).

The script is a build-time developer tool: it turns the IOC Multilingual
workbook, the AviList checklist and the BirdNET label set into the versioned
bundle shipped in ``echoroo/data/vernacular``. These tests cover the *pure*
matching layer with tiny in-memory fixtures so no xlsx (and no ``openpyxl``)
is required.

The script lives outside the ``echoroo`` package, so — exactly like
``test_export_role_permissions.py`` — it is imported via ``importlib.util``
from a path discovered by walking upward from this file.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# Path to the script under test
# ---------------------------------------------------------------------------

_SCRIPT_RELATIVE_PATH = Path("scripts") / "build_vernacular_bundle.py"


def _resolve_script_path() -> Path:
    override = os.environ.get("ECHOROO_BUILD_VERNACULAR_SCRIPT_PATH")
    if override:
        return Path(override)

    this_file = Path(__file__).resolve()
    candidates = [
        *(parent / _SCRIPT_RELATIVE_PATH for parent in this_file.parents),
        # Common dev-container location: apps/api/scripts is not bind-mounted,
        # so the script is copied in for local in-container runs.
        Path("/tmp/build_vernacular_bundle.py"),  # noqa: S108
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    # Fall back to the first candidate so the failure names a canonical path.
    return candidates[0]


_SCRIPT_PATH = _resolve_script_path()


_MODULE_NAME = "_build_vernacular_bundle_under_test"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # ``@dataclass`` resolves string annotations through
    # ``sys.modules[cls.__module__]``, so the module must be registered
    # *before* exec_module or every dataclass in the script blows up.
    sys.modules[_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(_MODULE_NAME, None)
        raise
    return module


# ---------------------------------------------------------------------------
# Fixtures — a miniature AviList
# ---------------------------------------------------------------------------


def _species(script: ModuleType) -> list[object]:
    """Four AviList species covering every matching branch.

    * ``Passer montanus``   — matched exactly by scientific name.
    * ``Tachyspiza gularis`` — BirdNET still calls it ``Accipiter gularis``;
      only the Clements English name ("Japanese Sparrowhawk") bridges them.
    * ``Ambiguous alpha`` / ``Ambiguous beta`` — share one English name, so
      rule 2 must refuse to guess and rule 3 (override) has to settle it.
    """
    cls = script.AviListSpecies
    return [
        cls(
            scientific_name="Passer montanus",
            english_name_clements="Eurasian Tree Sparrow",
            cornell_code="eutspa",
            avibase_id="avibase-C22FBF8D",
        ),
        cls(
            scientific_name="Tachyspiza gularis",
            english_name_clements="Japanese Sparrowhawk",
            cornell_code="japspa1",
            avibase_id="avibase-1E49FE52",
        ),
        cls(
            scientific_name="Ambiguous alpha",
            english_name_clements="Shared English Name",
            cornell_code="amba1",
            avibase_id="avibase-AAAA1111",
        ),
        cls(
            scientific_name="Ambiguous beta",
            english_name_clements="Shared English Name",
            cornell_code="ambb1",
            avibase_id="avibase-BBBB2222",
        ),
    ]


# ---------------------------------------------------------------------------
# parse_birdnet_label(s)
# ---------------------------------------------------------------------------


def test_parse_label_handles_underscore_scientific_form(script: ModuleType) -> None:
    """The packaged ``Genus_species_Common Name`` label format."""
    assert script.parse_birdnet_label("Turdus_merula_Eurasian Blackbird") == (
        "Turdus merula",
        "Eurasian Blackbird",
    )


def test_parse_label_handles_spaced_scientific_form(script: ModuleType) -> None:
    """The model-directory ``Genus species_Common Name`` label format."""
    assert script.parse_birdnet_label("Passer montanus_Eurasian Tree Sparrow") == (
        "Passer montanus",
        "Eurasian Tree Sparrow",
    )


def test_parse_label_handles_non_biological_single_token(script: ModuleType) -> None:
    assert script.parse_birdnet_label("Engine_Engine") == ("Engine", "Engine")


def test_parse_labels_skips_blank_lines(script: ModuleType) -> None:
    parsed = script.parse_birdnet_labels(
        ["Passer montanus_Eurasian Tree Sparrow", "", "   ", "Engine_Engine"]
    )
    assert parsed == [
        ("Passer montanus", "Eurasian Tree Sparrow"),
        ("Engine", "Engine"),
    ]


# ---------------------------------------------------------------------------
# build_clements_english_index()
# ---------------------------------------------------------------------------


def test_clements_index_drops_ambiguous_english_names(script: ModuleType) -> None:
    index = script.build_clements_english_index(_species(script))
    assert "japanese sparrowhawk" in index
    # "Shared English Name" is claimed by two species → not usable as a key.
    assert "shared english name" not in index


def test_clements_index_is_case_and_whitespace_insensitive(
    script: ModuleType,
) -> None:
    index = script.build_clements_english_index(_species(script))
    assert index["eurasian tree sparrow"].scientific_name == "Passer montanus"


# ---------------------------------------------------------------------------
# match_birdnet_labels() — matching order
# ---------------------------------------------------------------------------


def test_exact_scientific_name_match_wins(script: ModuleType) -> None:
    result = script.match_birdnet_labels(
        [("Passer montanus", "Eurasian Tree Sparrow")], _species(script)
    )
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.avilist_scientific_name == "Passer montanus"
    assert row.match_method == script.MATCH_EXACT
    assert row.avibase_id == "avibase-C22FBF8D"
    assert row.cornell_code == "eutspa"
    assert result.unresolved == []


def test_clements_english_bridges_a_genus_revision(script: ModuleType) -> None:
    """BirdNET's eBird genus is stale; the English name still identifies it."""
    result = script.match_birdnet_labels(
        [("Accipiter gularis", "Japanese Sparrowhawk")], _species(script)
    )
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.birdnet_scientific_name == "Accipiter gularis"
    assert row.avilist_scientific_name == "Tachyspiza gularis"
    assert row.match_method == script.MATCH_CLEMENTS_ENGLISH


def test_ambiguous_english_name_is_not_guessed(script: ModuleType) -> None:
    result = script.match_birdnet_labels(
        [("Unknown species", "Shared English Name")], _species(script)
    )
    assert result.rows == []
    assert result.unresolved == [("Unknown species", "Shared English Name")]


def test_override_resolves_what_the_other_rules_cannot(script: ModuleType) -> None:
    result = script.match_birdnet_labels(
        [("Unknown species", "Shared English Name")],
        _species(script),
        {"Unknown species": "Ambiguous beta"},
    )
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.avilist_scientific_name == "Ambiguous beta"
    assert row.match_method == script.MATCH_OVERRIDE
    assert result.unresolved == []


def test_override_never_outranks_an_exact_match(script: ModuleType) -> None:
    """Rule 1 runs first — an override cannot hijack a valid exact match."""
    result = script.match_birdnet_labels(
        [("Passer montanus", "Eurasian Tree Sparrow")],
        _species(script),
        {"Passer montanus": "Ambiguous beta"},
    )
    assert result.rows[0].avilist_scientific_name == "Passer montanus"
    assert result.rows[0].match_method == script.MATCH_EXACT


def test_override_pointing_at_an_unknown_species_is_ignored(
    script: ModuleType,
) -> None:
    result = script.match_birdnet_labels(
        [("Unknown species", "Shared English Name")],
        _species(script),
        {"Unknown species": "Not in avilist"},
    )
    assert result.rows == []
    assert result.unresolved == [("Unknown species", "Shared English Name")]


def test_non_biological_labels_land_in_unresolved(script: ModuleType) -> None:
    result = script.match_birdnet_labels(
        [("Engine", "Engine"), ("Dog", "Dog")], _species(script)
    )
    assert result.rows == []
    assert result.unresolved == [("Dog", "Dog"), ("Engine", "Engine")]


def test_identical_names_still_emit_a_row(script: ModuleType) -> None:
    """The AvibaseID / Cornell code make even a no-op mapping worth keeping."""
    result = script.match_birdnet_labels(
        [("Passer montanus", "Eurasian Tree Sparrow")], _species(script)
    )
    assert result.rows[0].birdnet_scientific_name == (
        result.rows[0].avilist_scientific_name
    )


def test_duplicate_labels_collapse_to_one_row(script: ModuleType) -> None:
    result = script.match_birdnet_labels(
        [
            ("Passer montanus", "Eurasian Tree Sparrow"),
            ("Passer montanus", "Eurasian Tree Sparrow"),
        ],
        _species(script),
    )
    assert len(result.rows) == 1


def test_method_counts_summarise_the_result(script: ModuleType) -> None:
    result = script.match_birdnet_labels(
        [
            ("Passer montanus", "Eurasian Tree Sparrow"),
            ("Accipiter gularis", "Japanese Sparrowhawk"),
            ("Unknown species", "Shared English Name"),
            ("Engine", "Engine"),
        ],
        _species(script),
        {"Unknown species": "Ambiguous alpha"},
    )
    assert result.method_counts == {
        script.MATCH_EXACT: 1,
        script.MATCH_CLEMENTS_ENGLISH: 1,
        script.MATCH_OVERRIDE: 1,
    }
    assert result.unresolved == [("Engine", "Engine")]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_crosswalk_rows_are_sorted_regardless_of_input_order(
    script: ModuleType,
) -> None:
    labels = [
        ("Passer montanus", "Eurasian Tree Sparrow"),
        ("Ambiguous alpha", "Shared English Name"),
        ("Accipiter gularis", "Japanese Sparrowhawk"),
    ]
    forward = script.match_birdnet_labels(labels, _species(script))
    reverse = script.match_birdnet_labels(
        list(reversed(labels)), list(reversed(_species(script)))
    )
    assert [row.as_row() for row in forward.rows] == [
        row.as_row() for row in reverse.rows
    ]
    assert [row.birdnet_scientific_name for row in forward.rows] == [
        "Accipiter gularis",
        "Ambiguous alpha",
        "Passer montanus",
    ]


def test_unresolved_entries_are_sorted(script: ModuleType) -> None:
    result = script.match_birdnet_labels(
        [("Zebra unknown", "Z"), ("Alpha unknown", "A")], _species(script)
    )
    assert result.unresolved == [("Alpha unknown", "A"), ("Zebra unknown", "Z")]


def test_sort_name_rows_dedupes_and_orders(script: ModuleType) -> None:
    rows = script.sort_name_rows(
        [
            ("  Zosterops japonicus ", " メジロ "),
            ("Passer montanus", "スズメ"),
            ("Passer montanus", "スズメ (duplicate)"),
            ("", "ignored"),
            ("Ignored", ""),
        ]
    )
    assert rows == [
        ("Passer montanus", "スズメ"),
        ("Zosterops japonicus", "メジロ"),
    ]


def test_write_csv_uses_lf_and_no_bom(script: ModuleType, tmp_path: Path) -> None:
    target = tmp_path / "out.csv"
    written = script.write_csv(target, ["a", "b"], [["1", "スズメ"], ["2", "メジロ"]])
    raw = target.read_bytes()
    assert written == 2
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    assert raw.decode("utf-8") == "a,b\n1,スズメ\n2,メジロ\n"


def test_write_json_is_sorted_and_newline_terminated(
    script: ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "meta.json"
    script.write_json(target, {"b": 2, "a": 1})
    text = target.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert text.index('"a"') < text.index('"b"')
    assert json.loads(text) == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# overrides.csv handling
# ---------------------------------------------------------------------------


def test_ensure_overrides_file_creates_header_only(
    script: ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "overrides.csv"
    script.ensure_overrides_file(target)
    assert target.read_text(encoding="utf-8") == (
        "birdnet_scientific_name,avilist_scientific_name\n"
    )
    assert script.read_overrides(target) == {}


def test_ensure_overrides_file_never_clobbers_curated_rows(
    script: ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "overrides.csv"
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["birdnet_scientific_name", "avilist_scientific_name"])
        writer.writerow(["Accipiter gentilis", "Astur gentilis"])
    script.ensure_overrides_file(target)
    assert script.read_overrides(target) == {"Accipiter gentilis": "Astur gentilis"}


def test_read_overrides_missing_file_is_empty(
    script: ModuleType, tmp_path: Path
) -> None:
    assert script.read_overrides(tmp_path / "nope.csv") == {}
