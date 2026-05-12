"""Coverage uplift unit tests for ``echoroo.api.v1.search.similarity``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers search_similar (ValueError path),
search_similar_by_audio (file size, extension, service call paths), and
get_embedding_stats handlers so the module clears the 85% threshold
without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from echoroo.api.v1.search import similarity as mod


def _make_service() -> MagicMock:
    svc = MagicMock()
    svc.search_by_embedding_id = AsyncMock()
    svc.search_by_audio_file = AsyncMock()
    svc.get_embedding_stats = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_search_similar_raises_404_on_value_error() -> None:
    """search_similar raises 404 when service raises ValueError (lines 89-90)."""
    service = _make_service()
    service.search_by_embedding_id = AsyncMock(
        side_effect=ValueError("embedding not found")
    )
    from echoroo.schemas.search import SimilaritySearchRequest

    request = SimilaritySearchRequest(
        embedding_id=uuid4(),
        model_name="perch",
        limit=10,
        min_similarity=0.5,
        dataset_id=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        await mod.search_similar(
            project_id=uuid4(),
            request=request,
            service=service,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "embedding not found" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_search_similar_success() -> None:
    """search_similar delegates to service and returns result (lines 85-87)."""
    service = _make_service()
    sentinel = MagicMock()
    service.search_by_embedding_id = AsyncMock(return_value=sentinel)
    from echoroo.schemas.search import SimilaritySearchRequest

    request = SimilaritySearchRequest(
        embedding_id=uuid4(),
        model_name="perch",
        limit=10,
        min_similarity=0.5,
        dataset_id=None,
    )

    result = await mod.search_similar(
        project_id=uuid4(),
        request=request,
        service=service,
    )
    assert result is sentinel


@pytest.mark.asyncio
async def test_search_similar_by_audio_raises_413_on_too_large() -> None:
    """search_similar_by_audio raises 413 when file exceeds limit (lines 151-154)."""
    service = _make_service()
    audio_file = MagicMock()
    audio_file.filename = "sound.wav"
    # Content that exceeds MAX_AUDIO_UPLOAD_SIZE
    audio_file.read = AsyncMock(return_value=b"x" * (mod.MAX_AUDIO_UPLOAD_SIZE + 1))

    with pytest.raises(HTTPException) as exc_info:
        await mod.search_similar_by_audio(
            project_id=uuid4(),
            service=service,
            audio_file=audio_file,
            model_name="perch",
            limit=20,
            min_similarity=0.5,
            dataset_id=None,
        )

    assert exc_info.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE


@pytest.mark.asyncio
async def test_search_similar_by_audio_raises_400_on_bad_extension() -> None:
    """search_similar_by_audio raises 400 for unsupported extension (lines 159-162)."""
    service = _make_service()
    audio_file = MagicMock()
    audio_file.filename = "sound.xyz"
    audio_file.read = AsyncMock(return_value=b"small content")

    with pytest.raises(HTTPException) as exc_info:
        await mod.search_similar_by_audio(
            project_id=uuid4(),
            service=service,
            audio_file=audio_file,
            model_name="perch",
            limit=20,
            min_similarity=0.5,
            dataset_id=None,
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Unsupported file type" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_search_similar_by_audio_raises_422_on_file_not_found() -> None:
    """search_similar_by_audio raises 422 on FileNotFoundError (lines 180-182)."""
    service = _make_service()
    service.search_by_audio_file = AsyncMock(side_effect=FileNotFoundError("model not found"))
    audio_file = MagicMock()
    audio_file.filename = "sound.wav"
    audio_file.read = AsyncMock(return_value=b"small content")

    mock_tmp_file = MagicMock()
    mock_tmp_file.name = "/tmp/test.wav"
    mock_tmp_ctx = MagicMock()
    mock_tmp_ctx.__enter__ = MagicMock(return_value=mock_tmp_file)
    mock_tmp_ctx.__exit__ = MagicMock(return_value=False)

    with (
        patch("tempfile.NamedTemporaryFile", return_value=mock_tmp_ctx),
        patch("pathlib.Path.unlink", return_value=None),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.search_similar_by_audio(
            project_id=uuid4(),
            service=service,
            audio_file=audio_file,
            model_name="perch",
            limit=20,
            min_similarity=0.5,
            dataset_id=None,
        )

    assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_search_similar_by_audio_raises_422_on_value_error() -> None:
    """search_similar_by_audio raises 422 on ValueError from service (lines 185-186)."""
    service = _make_service()
    service.search_by_audio_file = AsyncMock(side_effect=ValueError("invalid model"))
    audio_file = MagicMock()
    audio_file.filename = "sound.wav"
    audio_file.read = AsyncMock(return_value=b"small content")

    mock_tmp_file = MagicMock()
    mock_tmp_file.name = "/tmp/test.wav"
    mock_tmp_ctx = MagicMock()
    mock_tmp_ctx.__enter__ = MagicMock(return_value=mock_tmp_file)
    mock_tmp_ctx.__exit__ = MagicMock(return_value=False)

    with (
        patch("tempfile.NamedTemporaryFile", return_value=mock_tmp_ctx),
        patch("pathlib.Path.unlink", return_value=None),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.search_similar_by_audio(
            project_id=uuid4(),
            service=service,
            audio_file=audio_file,
            model_name="perch",
            limit=20,
            min_similarity=0.5,
            dataset_id=None,
        )

    assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_get_embedding_stats_delegates_to_service() -> None:
    """get_embedding_stats delegates to service (line 230)."""
    service = _make_service()
    sentinel = MagicMock()
    service.get_embedding_stats = AsyncMock(return_value=sentinel)
    project_id = uuid4()

    result = await mod.get_embedding_stats(
        project_id=project_id,
        service=service,
        dataset_id=None,
    )
    assert result is sentinel
    service.get_embedding_stats.assert_awaited_once_with(
        project_id=project_id,
        dataset_id=None,
    )
