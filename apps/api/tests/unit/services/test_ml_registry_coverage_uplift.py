"""Coverage uplift unit tests for ``echoroo.ml.registry``.

Phase 17 §C heavy-gap batch: covers the registration update path (line
141), the ``unregister`` happy path (lines 166-170), the lookup raising
(line 191), the ``ModelNotFoundError`` raise body (lines 249-255), the
``get_engine_class`` lookup (line 212), the ``get_model_info`` getter
(line 228), the ``is_registered`` predicate (line 266) (also lines
228, 266 from existing call sites), the ``list_models`` snapshot
(line 293), and the ``clear`` reset (lines 301-302) so the module
clears the 85% threshold without touching production code.
"""

from __future__ import annotations

import pytest

from echoroo.ml.registry import ModelNotFoundError, ModelRegistry


class _FakeLoader:
    """Stand-in for :class:`ModelLoader` that does not import heavy ML libs."""


class _FakeEngine:
    """Stand-in for :class:`InferenceEngine`."""


@pytest.fixture(autouse=True)
def _isolate_registry() -> None:
    """Reset the global registry before each test so cases stay isolated."""
    ModelRegistry.clear()
    yield
    ModelRegistry.clear()


def test_register_then_get_loader_and_engine_class() -> None:
    """register() adds a model and get_*_class() returns it (lines 191, 212)."""
    ModelRegistry.register(
        name="fake",
        loader_class=_FakeLoader,
        engine_class=_FakeEngine,
        description="unit test",
    )
    assert ModelRegistry.get_loader_class("fake") is _FakeLoader
    assert ModelRegistry.get_engine_class("fake") is _FakeEngine


def test_register_idempotent_update_existing(caplog: pytest.LogCaptureFixture) -> None:
    """Registering the same name twice updates the entry (line 141)."""
    ModelRegistry.register("fake", _FakeLoader, _FakeEngine, "v1")
    ModelRegistry.register("fake", _FakeLoader, _FakeEngine, "v2")
    info = ModelRegistry.get_model_info("fake")
    assert info is not None
    assert info.description == "v2"


def test_unregister_removes_existing_model() -> None:
    """unregister() deletes a registered model (lines 166-170)."""
    ModelRegistry.register("fake", _FakeLoader, _FakeEngine)
    assert ModelRegistry.unregister("fake") is True
    assert ModelRegistry.is_registered("fake") is False


def test_unregister_unknown_model_returns_false() -> None:
    """unregister() returns False when the model was not registered."""
    assert ModelRegistry.unregister("missing") is False


def test_get_loader_class_raises_when_unknown() -> None:
    """get_loader_class() raises ModelNotFoundError (lines 249-255)."""
    with pytest.raises(ModelNotFoundError) as exc_info:
        ModelRegistry.get_loader_class("nope")
    assert "nope" in str(exc_info.value)
    assert "Available models" in str(exc_info.value)


def test_get_engine_class_raises_when_unknown() -> None:
    """get_engine_class() raises ModelNotFoundError (line 212 negative)."""
    with pytest.raises(ModelNotFoundError):
        ModelRegistry.get_engine_class("nope")


def test_get_model_info_returns_none_when_unknown() -> None:
    """get_model_info() returns None when not registered (line 228)."""
    assert ModelRegistry.get_model_info("nope") is None


def test_available_models_and_list_models_snapshot() -> None:
    """available_models() and list_models() reflect current state (lines 266, 293)."""
    ModelRegistry.register("a", _FakeLoader, _FakeEngine)
    ModelRegistry.register("b", _FakeLoader, _FakeEngine)
    assert ModelRegistry.available_models() == ["a", "b"]
    info_list = ModelRegistry.list_models()
    assert {info.name for info in info_list} == {"a", "b"}
    assert ModelRegistry.is_registered("a") is True
    assert ModelRegistry.is_registered("missing") is False


def test_clear_empties_registry(caplog: pytest.LogCaptureFixture) -> None:
    """clear() removes all entries (lines 301-302)."""
    ModelRegistry.register("a", _FakeLoader, _FakeEngine)
    ModelRegistry.clear()
    assert ModelRegistry.available_models() == []
