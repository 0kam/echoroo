"""Unit tests for locale-aware palette common-name resolution (WS-A 和名 fix).

``AnnotationSetService._build_palette`` previously returned ``common_name=None``
for every entry. It now resolves the display name from the LOCAL database via
``resolve_vernacular_names`` (requested-locale → English fallback).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from echoroo.services.annotation_set import AnnotationSetService


def _make_service() -> AnnotationSetService:
    set_repo = MagicMock()
    set_repo.db = MagicMock()
    set_repo.list_palette_with_taxa = AsyncMock()
    segment_repo = MagicMock()
    return AnnotationSetService(set_repo=set_repo, segment_repo=segment_repo)


@pytest.mark.asyncio
async def test_build_palette_resolves_ja_common_name() -> None:
    """locale=ja → entry's common_name is the ja vernacular when present."""
    service = _make_service()
    taxon_id = uuid4()
    taxon = SimpleNamespace(id=taxon_id, scientific_name="Hirundo rustica")
    service.set_repo.list_palette_with_taxa = AsyncMock(return_value=[(taxon, 0)])

    with patch(
        "echoroo.services.annotation_set.resolve_vernacular_names",
        new=AsyncMock(return_value={taxon_id: "ツバメ"}),
    ) as mock_resolve:
        palette = await service._build_palette(uuid4(), locale="ja")

    assert len(palette) == 1
    assert palette[0].common_name == "ツバメ"
    assert palette[0].scientific_name == "Hirundo rustica"
    # The requested locale is threaded into the resolver.
    _, _, called_locale = mock_resolve.await_args.args
    assert called_locale == "ja"


@pytest.mark.asyncio
async def test_build_palette_defaults_to_en_when_no_locale() -> None:
    """Default locale resolves the English name."""
    service = _make_service()
    taxon_id = uuid4()
    taxon = SimpleNamespace(id=taxon_id, scientific_name="Parus major")
    service.set_repo.list_palette_with_taxa = AsyncMock(return_value=[(taxon, 0)])

    with patch(
        "echoroo.services.annotation_set.resolve_vernacular_names",
        new=AsyncMock(return_value={taxon_id: "Great Tit"}),
    ):
        palette = await service._build_palette(uuid4())

    assert palette[0].common_name == "Great Tit"


@pytest.mark.asyncio
async def test_build_palette_common_name_none_when_unresolved() -> None:
    """No vernacular row → common_name stays None (scientific floor downstream)."""
    service = _make_service()
    taxon_id = uuid4()
    taxon = SimpleNamespace(id=taxon_id, scientific_name="Unknownus testus")
    service.set_repo.list_palette_with_taxa = AsyncMock(return_value=[(taxon, 0)])

    with patch(
        "echoroo.services.annotation_set.resolve_vernacular_names",
        new=AsyncMock(return_value={}),
    ):
        palette = await service._build_palette(uuid4(), locale="ja")

    assert palette[0].common_name is None
