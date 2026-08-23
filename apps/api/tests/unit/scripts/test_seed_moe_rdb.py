"""Unit tests for the MoE Red Data Book seeder (WS-A v2 slice 4).

Migration 0034 re-keyed ``taxon_sensitivities.taxon_id`` onto ``taxa.id``, so
the CSV contract changed from a ``taxon_id`` GBIF-key column to a
``scientific_name`` column that the seeder resolves against the local ``taxa``
table.

The important behavioural split pinned here:

* a name with no local counterpart is **warned, counted and skipped** — one
  stale name from a new RDB edition must not discard the whole import;
* a malformed / out-of-range ``sensitivity_h3_res`` still **aborts** — that is
  an operator typo with masking consequences (FR-027), not upstream drift.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from echoroo.models.enums import TaxonSensitivitySource
from echoroo.scripts import seed_moe_rdb


class _StubSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> _StubSession:
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.fixture
def patched_seeder(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    session = _StubSession()
    state: dict[str, Any] = {
        "session": session,
        "upserts": [],
        "known": {},
        "resolve_calls": 0,
    }

    monkeypatch.setattr(seed_moe_rdb, "AsyncSessionLocal", lambda: session)

    async def _resolve(_session: Any, names: Any) -> dict[str, UUID]:
        state["resolve_calls"] += 1
        materialised = [n.strip() for n in names if n and n.strip()]
        return {n: state["known"][n] for n in materialised if n in state["known"]}

    monkeypatch.setattr(
        seed_moe_rdb, "resolve_taxon_ids_by_scientific_name", _resolve
    )

    async def _upsert(_session: Any, **kwargs: Any) -> tuple[bool, int | None]:
        state["upserts"].append(kwargs)
        return False, None

    monkeypatch.setattr(seed_moe_rdb, "upsert_taxon_sensitivity", _upsert)
    return state


def _write_csv(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "rdb.csv"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.mark.asyncio
async def test_resolvable_rows_are_upserted_against_taxa_ids(
    tmp_path: Path, patched_seeder: dict[str, Any]
) -> None:
    taxon_uuid = uuid4()
    patched_seeder["known"] = {"Nipponia nippon": taxon_uuid}
    csv_path = _write_csv(
        tmp_path,
        "scientific_name,category,sensitivity_h3_res,notes\n"
        "Nipponia nippon,CR,5,Endemic to Sado\n",
    )

    summary = await seed_moe_rdb._seed_csv(csv_path)

    assert summary == {"upserted": 1, "skipped": 0, "unresolved": 0}
    upsert = patched_seeder["upserts"][0]
    assert upsert["taxon_id"] == taxon_uuid
    assert upsert["source"] is TaxonSensitivitySource.MOE_RDB
    assert upsert["sensitivity_h3_res"] == 5
    assert upsert["category"] == "CR"
    assert upsert["notes"] == "Endemic to Sado"
    assert patched_seeder["session"].committed is True


@pytest.mark.asyncio
async def test_unresolvable_row_is_skipped_and_counted(
    tmp_path: Path, patched_seeder: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """A stale name must not abort the import — the good rows still land."""
    taxon_uuid = uuid4()
    patched_seeder["known"] = {"Nipponia nippon": taxon_uuid}
    csv_path = _write_csv(
        tmp_path,
        "scientific_name,category,sensitivity_h3_res,notes\n"
        "Nipponia nippon,CR,5,\n"
        "Absolutely nonexistens,EN,5,\n",
    )

    with caplog.at_level("WARNING", logger=seed_moe_rdb.logger.name):
        summary = await seed_moe_rdb._seed_csv(csv_path)

    assert summary == {"upserted": 1, "skipped": 0, "unresolved": 1}
    assert [u["taxon_id"] for u in patched_seeder["upserts"]] == [taxon_uuid]
    assert any(
        "Absolutely nonexistens" in record.getMessage() for record in caplog.records
    )
    assert patched_seeder["session"].committed is True


@pytest.mark.asyncio
async def test_blank_scientific_name_counts_as_skipped_not_unresolved(
    tmp_path: Path, patched_seeder: dict[str, Any]
) -> None:
    patched_seeder["known"] = {}
    csv_path = _write_csv(
        tmp_path,
        "scientific_name,category,sensitivity_h3_res,notes\n" ",CR,5,\n",
    )

    summary = await seed_moe_rdb._seed_csv(csv_path)

    assert summary == {"upserted": 0, "skipped": 1, "unresolved": 0}


@pytest.mark.asyncio
async def test_out_of_range_h3_res_still_aborts(
    tmp_path: Path, patched_seeder: dict[str, Any]
) -> None:
    """FR-027 violations are operator typos and must roll the import back."""
    patched_seeder["known"] = {"Nipponia nippon": uuid4()}
    csv_path = _write_csv(
        tmp_path,
        "scientific_name,category,sensitivity_h3_res,notes\n"
        "Nipponia nippon,CR,3,\n",
    )

    with pytest.raises(ValueError, match="FR-027"):
        await seed_moe_rdb._seed_csv(csv_path)

    assert patched_seeder["session"].rolled_back is True
    assert patched_seeder["session"].committed is False


@pytest.mark.asyncio
async def test_non_integer_h3_res_still_aborts(
    tmp_path: Path, patched_seeder: dict[str, Any]
) -> None:
    patched_seeder["known"] = {"Nipponia nippon": uuid4()}
    csv_path = _write_csv(
        tmp_path,
        "scientific_name,category,sensitivity_h3_res,notes\n"
        "Nipponia nippon,CR,coarse,\n",
    )

    with pytest.raises(ValueError):
        await seed_moe_rdb._seed_csv(csv_path)

    assert patched_seeder["session"].rolled_back is True


@pytest.mark.asyncio
async def test_names_resolved_in_one_bulk_call(
    tmp_path: Path, patched_seeder: dict[str, Any]
) -> None:
    patched_seeder["known"] = {f"Genus species{i}": uuid4() for i in range(4)}
    rows = "".join(f"Genus species{i},VU,7,\n" for i in range(4))
    csv_path = _write_csv(
        tmp_path, "scientific_name,category,sensitivity_h3_res,notes\n" + rows
    )

    summary = await seed_moe_rdb._seed_csv(csv_path)

    assert summary["upserted"] == 4
    assert patched_seeder["resolve_calls"] == 1


# ---------------------------------------------------------------------------
# Strictest-wins collapse (Codex finding 5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_taxon_collapses_to_strictest(
    tmp_path: Path, patched_seeder: dict[str, Any]
) -> None:
    """Two CSV rows on one taxon -> ONE upsert at the strictest resolution."""
    taxon_uuid = uuid4()
    patched_seeder["known"] = {
        "Accipiter gularis": taxon_uuid,
        "Tachyspiza gularis": taxon_uuid,
    }
    csv_path = _write_csv(
        tmp_path,
        "scientific_name,category,sensitivity_h3_res,notes\n"
        "Accipiter gularis,EN,5,strict\n"
        "Tachyspiza gularis,LC,9,loose\n",
    )

    summary = await seed_moe_rdb._seed_csv(csv_path)

    assert summary == {"upserted": 1, "skipped": 0, "unresolved": 0}
    assert len(patched_seeder["upserts"]) == 1
    assert patched_seeder["upserts"][0]["sensitivity_h3_res"] == 5
    assert patched_seeder["upserts"][0]["category"] == "EN"
    assert patched_seeder["upserts"][0]["notes"] == "strict"


@pytest.mark.asyncio
async def test_duplicate_taxon_collapse_is_order_independent(
    tmp_path: Path, patched_seeder: dict[str, Any]
) -> None:
    """Row order must not decide how strongly a species is masked."""
    taxon_uuid = uuid4()
    patched_seeder["known"] = {
        "Accipiter gularis": taxon_uuid,
        "Tachyspiza gularis": taxon_uuid,
    }
    csv_path = _write_csv(
        tmp_path,
        "scientific_name,category,sensitivity_h3_res,notes\n"
        "Tachyspiza gularis,LC,9,loose\n"
        "Accipiter gularis,EN,5,strict\n",
    )

    summary = await seed_moe_rdb._seed_csv(csv_path)

    assert summary["upserted"] == 1
    assert len(patched_seeder["upserts"]) == 1
    assert patched_seeder["upserts"][0]["sensitivity_h3_res"] == 5


# ---------------------------------------------------------------------------
# CSV header contract (non-blocking finding)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_0034_csv_header_fails_fast_with_a_hint(
    tmp_path: Path, patched_seeder: dict[str, Any]
) -> None:
    """An old ``taxon_id``-shaped CSV must say so, not report N skipped rows."""
    csv_path = _write_csv(
        tmp_path,
        "taxon_id,category,sensitivity_h3_res,notes\n1234567,CR,5,\n",
    )

    with pytest.raises(seed_moe_rdb.CsvContractError) as excinfo:
        await seed_moe_rdb._seed_csv(csv_path)

    message = str(excinfo.value)
    assert "scientific_name" in message
    assert "pre-0034" in message
    # Nothing may have been attempted against the DB.
    assert patched_seeder["upserts"] == []
    assert patched_seeder["resolve_calls"] == 0


@pytest.mark.asyncio
async def test_missing_h3_column_fails_fast(
    tmp_path: Path, patched_seeder: dict[str, Any]
) -> None:
    csv_path = _write_csv(
        tmp_path, "scientific_name,category,notes\nNipponia nippon,CR,\n"
    )

    with pytest.raises(seed_moe_rdb.CsvContractError, match="sensitivity_h3_res"):
        await seed_moe_rdb._seed_csv(csv_path)


def test_validate_header_accepts_the_documented_contract() -> None:
    seed_moe_rdb._validate_header(
        ["scientific_name", "category", "sensitivity_h3_res", "notes"]
    )
    # Optional columns may be absent.
    seed_moe_rdb._validate_header(["scientific_name", "sensitivity_h3_res"])


def test_validate_header_rejects_empty_header() -> None:
    with pytest.raises(seed_moe_rdb.CsvContractError):
        seed_moe_rdb._validate_header(None)


# ---------------------------------------------------------------------------
# CLI exit codes (non-blocking finding)
# ---------------------------------------------------------------------------


def test_main_exits_non_zero_when_nothing_was_upserted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rows processed but none imported is a misconfiguration, not success."""
    csv_path = _write_csv(
        tmp_path,
        "scientific_name,category,sensitivity_h3_res,notes\n"
        "Absolutely nonexistens,CR,5,\n",
    )

    async def _fake_seed(_path: Path) -> dict[str, int]:
        return {"upserted": 0, "skipped": 0, "unresolved": 1}

    monkeypatch.setattr(seed_moe_rdb, "_seed_csv", _fake_seed)

    assert seed_moe_rdb.main([str(csv_path), "--confirm"]) == 4


def test_main_exits_zero_when_rows_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = _write_csv(
        tmp_path,
        "scientific_name,category,sensitivity_h3_res,notes\nNipponia nippon,CR,5,\n",
    )

    async def _fake_seed(_path: Path) -> dict[str, int]:
        return {"upserted": 1, "skipped": 0, "unresolved": 3}

    monkeypatch.setattr(seed_moe_rdb, "_seed_csv", _fake_seed)

    assert seed_moe_rdb.main([str(csv_path), "--confirm"]) == 0


def test_main_exits_zero_on_an_empty_but_valid_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No rows at all is a no-op, not a failure."""
    csv_path = _write_csv(
        tmp_path, "scientific_name,category,sensitivity_h3_res,notes\n"
    )

    async def _fake_seed(_path: Path) -> dict[str, int]:
        return {"upserted": 0, "skipped": 0, "unresolved": 0}

    monkeypatch.setattr(seed_moe_rdb, "_seed_csv", _fake_seed)

    assert seed_moe_rdb.main([str(csv_path), "--confirm"]) == 0


def test_main_reports_a_header_contract_error_distinctly(
    tmp_path: Path
) -> None:
    csv_path = _write_csv(
        tmp_path, "taxon_id,category,sensitivity_h3_res,notes\n1234567,CR,5,\n"
    )

    assert seed_moe_rdb.main([str(csv_path), "--confirm"]) == 5
