"""Coverage uplift unit tests for ``echoroo.workers.db_utils``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers get_worker_engine_and_session_factory
so the module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from echoroo.workers.db_utils import get_worker_engine_and_session_factory


def test_get_worker_engine_returns_engine_and_session_factory() -> None:
    """get_worker_engine_and_session_factory() returns (engine, session_factory) (lines 56-67)."""
    mock_engine = MagicMock()
    mock_session_factory = MagicMock()

    with (
        patch(
            "echoroo.workers.db_utils.create_async_engine", return_value=mock_engine
        ) as mock_create_engine,
        patch(
            "echoroo.workers.db_utils.async_sessionmaker", return_value=mock_session_factory
        ) as mock_sessionmaker,
    ):
        engine, factory = get_worker_engine_and_session_factory()

    assert engine is mock_engine
    assert factory is mock_session_factory
    mock_create_engine.assert_called_once()
    mock_sessionmaker.assert_called_once()


def test_get_worker_engine_uses_settings_database_url() -> None:
    """get_worker_engine_and_session_factory() reads DATABASE_URL from settings (line 57)."""
    mock_engine = MagicMock()
    mock_session_factory = MagicMock()
    captured_args: list[object] = []

    def capture_engine(*args: object, **kwargs: object) -> MagicMock:
        captured_args.extend(args)
        return mock_engine

    with (
        patch("echoroo.workers.db_utils.create_async_engine", side_effect=capture_engine),
        patch("echoroo.workers.db_utils.async_sessionmaker", return_value=mock_session_factory),
    ):
        get_worker_engine_and_session_factory()

    # The first positional arg should be the DATABASE_URL
    assert len(captured_args) >= 1
    assert isinstance(captured_args[0], str)
    assert "postgres" in captured_args[0] or "://" in captured_args[0]


def test_get_worker_engine_called_twice_returns_new_instances() -> None:
    """Each call to get_worker_engine_and_session_factory creates fresh engine (design intent)."""
    mock_engine_1 = MagicMock()
    mock_engine_2 = MagicMock()
    call_count = 0

    def create_engine_side_effect(*args: object, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        return mock_engine_1 if call_count == 1 else mock_engine_2

    with (
        patch(
            "echoroo.workers.db_utils.create_async_engine", side_effect=create_engine_side_effect
        ),
        patch("echoroo.workers.db_utils.async_sessionmaker", return_value=MagicMock()),
    ):
        engine1, _ = get_worker_engine_and_session_factory()
        engine2, _ = get_worker_engine_and_session_factory()

    assert call_count == 2
    assert engine1 is mock_engine_1
    assert engine2 is mock_engine_2
