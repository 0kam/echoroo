"""Test suite for plugin endpoints."""

from fastapi.testclient import TestClient


class TestPlugins:
    """Test plugin endpoints."""

    async def test_list_plugins(
        self,
        client: TestClient,
    ):
        """Test listing available plugins."""
        response = client.get("/api/v1/plugins/list/")
        assert response.status_code == 200
        content = response.json()
        assert isinstance(content, list)

    async def test_list_plugins_returns_plugin_info(
        self,
        client: TestClient,
    ):
        """Test that list_plugins returns proper plugin info."""
        response = client.get("/api/v1/plugins/list/")
        assert response.status_code == 200
        content = response.json()

        if content:  # If there are plugins
            plugin = content[0]
            assert "name" in plugin
            assert "version" in plugin
            assert "url" in plugin
            # Optional fields
            assert "description" in plugin
            assert "thumbnail" in plugin
            assert "attribution" in plugin

    async def test_list_plugins_returns_valid_structure(
        self,
        client: TestClient,
    ):
        """Test that list plugins returns valid JSON."""
        response = client.get("/api/v1/plugins/list/")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        content = response.json()
        assert isinstance(content, list)
