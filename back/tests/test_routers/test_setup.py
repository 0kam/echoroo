"""Test suite for the setup endpoints."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from whombat.system import create_app
from whombat.system.settings import (
    Settings,
    get_settings,
    load_settings_from_file,
    write_settings_to_file,
)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    base = tmp_path / "data"
    monkeypatch.setenv("WHOMBAT_DATA_DIR", str(base))
    return base


@pytest.fixture
def setup_settings(tmp_path, data_dir):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(exist_ok=True)
    settings = Settings(
        db_dialect="sqlite",
        db_name=str(tmp_path / "test.db"),
        audio_dir=audio_dir,
        open_on_startup=False,
        log_to_file=False,
        log_to_stdout=True,
    )
    write_settings_to_file(settings)
    get_settings.cache_clear()
    return settings


@pytest.fixture
def setup_client(setup_settings: Settings):
    app = create_app(setup_settings)
    app.dependency_overrides[get_settings] = lambda: setup_settings
    with TestClient(app) as client:
        yield client


def test_get_audio_directory_returns_current_value(
    setup_client: TestClient,
    setup_settings: Settings,
):
    response = setup_client.get("/api/v1/setup/audio_dir/")
    assert response.status_code == 200
    payload = response.json()
    assert Path(payload["audio_dir"]) == setup_settings.audio_dir


def test_update_audio_directory_persists_to_settings_file(
    setup_client: TestClient,
    tmp_path,
):
    new_dir = tmp_path / "new_audio"
    new_dir.mkdir()

    response = setup_client.post(
        "/api/v1/setup/audio_dir/",
        json={"audio_dir": str(new_dir)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert Path(payload["audio_dir"]) == new_dir.resolve()

    get_settings.cache_clear()
    updated = load_settings_from_file()
    assert updated.audio_dir == new_dir.resolve()
