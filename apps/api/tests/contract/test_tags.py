"""Contract tests for tag management endpoints.

Tests verify that endpoints conform to the OpenAPI specification for
User Story 3: Tag Management.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import TagCategory
from echoroo.models.project import Project
from echoroo.models.tag import Tag


@pytest.fixture
async def test_tag(db_session: AsyncSession, test_project: Project) -> Tag:
    """Create a test tag directly in the database.

    Args:
        db_session: Database session
        test_project: Test project to associate tag with

    Returns:
        Test tag instance
    """
    tag = Tag(
        project_id=test_project.id,
        name="Parus major",
        category=TagCategory.SPECIES,
        scientific_name="Parus major",
        common_name="Great tit",
        gbif_taxon_key=5788633,
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag


@pytest.fixture
def test_tag_id(test_tag: Tag) -> str:
    """Get test tag ID.

    Args:
        test_tag: Test tag

    Returns:
        Tag UUID as string
    """
    return str(test_tag.id)


@pytest.mark.asyncio
class TestTagListEndpoints:
    """Test tag listing and filtering endpoints."""

    async def test_list_tags_empty(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/tags - empty list initially."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/tags",
            headers=csrf_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
        assert isinstance(data["items"], list)
        assert data["total"] == 0
        assert data["page"] == 1

    async def test_list_tags_with_category_filter(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_tag: Tag,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/tags with category filter."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/tags",
            headers=csrf_headers,
            params={"category": "species"},
        )

        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["category"] == "species"

    async def test_list_tags_with_search_filter(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_tag: Tag,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/tags with search filter."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/tags",
            headers=csrf_headers,
            params={"search": "Parus"},
        )

        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert data["total"] >= 1

    async def test_list_tags_pagination(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_tag: Tag,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/tags pagination params."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/tags",
            headers=csrf_headers,
            params={"page": 1, "page_size": 10},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 1
        assert data["page_size"] == 10

    async def test_list_tags_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/tags requires authentication."""
        response = await client.get(f"/web-api/v1/projects/{test_project_id}/tags")

        assert response.status_code == 401


@pytest.mark.asyncio
class TestTagCreateEndpoints:
    """Test tag creation endpoints."""

    async def test_create_species_tag(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/tags - create species tag."""
        tag_data = {
            "name": "Turdus merula",
            "category": "species",
            "scientific_name": "Turdus merula",
            "common_name": "Common blackbird",
            "gbif_taxon_key": 5789399,
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/tags",
            headers=csrf_headers,
            json=tag_data,
        )

        assert response.status_code == 201
        data = response.json()

        assert "id" in data
        assert data["name"] == tag_data["name"]
        assert data["category"] == tag_data["category"]
        assert data["scientific_name"] == tag_data["scientific_name"]
        assert data["common_name"] == tag_data["common_name"]
        assert data["gbif_taxon_key"] == tag_data["gbif_taxon_key"]
        assert data["project_id"] == test_project_id
        assert data["parent_id"] is None
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_tag_with_parent_id(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_tag_id: str,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/tags - create tag with parent_id (hierarchy)."""
        tag_data = {
            "name": "Parus major subspecies",
            "category": "species",
            "parent_id": test_tag_id,
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/tags",
            headers=csrf_headers,
            json=tag_data,
        )

        assert response.status_code == 201
        data = response.json()

        assert data["parent_id"] == test_tag_id
        assert data["name"] == tag_data["name"]

    async def test_create_tag_validation_error(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/tags - validation error on empty name."""
        tag_data = {
            "name": "",  # empty name should fail validation
            "category": "species",
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/tags",
            headers=csrf_headers,
            json=tag_data,
        )

        assert response.status_code == 422

    async def test_create_tag_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/tags requires authentication."""
        tag_data = {"name": "Test Tag", "category": "species"}

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/tags",
            json=tag_data,
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestTagDetailEndpoints:
    """Test tag detail, update, and delete endpoints."""

    async def test_get_tag_detail(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_tag_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/tags/{tag_id} - get detail with children."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/tags/{test_tag_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == test_tag_id
        assert "project_id" in data
        assert "parent_id" in data
        assert "name" in data
        assert "category" in data
        assert "gbif_taxon_key" in data
        assert "scientific_name" in data
        assert "common_name" in data
        assert "created_at" in data
        assert "updated_at" in data
        assert "children" in data
        assert "usage_count" in data
        assert isinstance(data["children"], list)
        assert isinstance(data["usage_count"], int)

    async def test_get_tag_detail_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/tags/{tag_id} - not found."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/tags/{fake_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 404

    async def test_get_tag_detail_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_tag_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/tags/{tag_id} requires authentication."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/tags/{test_tag_id}",
        )

        assert response.status_code == 401

    async def test_update_tag(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_tag_id: str,
    ) -> None:
        """Test PATCH /web-api/v1/projects/{project_id}/tags/{tag_id} - update tag."""
        update_data = {
            "name": "Updated Parus major",
            "common_name": "Updated great tit",
        }

        response = await client.patch(
            f"/web-api/v1/projects/{test_project_id}/tags/{test_tag_id}",
            headers=csrf_headers,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["name"] == update_data["name"]
        assert data["common_name"] == update_data["common_name"]

    async def test_update_tag_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test PATCH /web-api/v1/projects/{project_id}/tags/{tag_id} - not found."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.patch(
            f"/web-api/v1/projects/{test_project_id}/tags/{fake_id}",
            headers=csrf_headers,
            json={"name": "Should Fail"},
        )

        assert response.status_code == 404

    async def test_update_tag_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_tag_id: str,
    ) -> None:
        """Test PATCH /web-api/v1/projects/{project_id}/tags/{tag_id} requires authentication."""
        response = await client.patch(
            f"/web-api/v1/projects/{test_project_id}/tags/{test_tag_id}",
            json={"name": "Should Fail"},
        )

        assert response.status_code == 401

    async def test_delete_tag(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test DELETE /web-api/v1/projects/{project_id}/tags/{tag_id} - delete tag."""
        # First create a tag to delete
        create_response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/tags",
            headers=csrf_headers,
            json={"name": "Tag To Delete", "category": "quality"},
        )
        assert create_response.status_code == 201
        tag_id = create_response.json()["id"]

        # Delete the tag
        response = await client.delete(
            f"/web-api/v1/projects/{test_project_id}/tags/{tag_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 204

        # Verify tag is deleted
        get_response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/tags/{tag_id}",
            headers=csrf_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_tag_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test DELETE /web-api/v1/projects/{project_id}/tags/{tag_id} - not found."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/web-api/v1/projects/{test_project_id}/tags/{fake_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 404

    async def test_delete_tag_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_tag_id: str,
    ) -> None:
        """Test DELETE /web-api/v1/projects/{project_id}/tags/{tag_id} requires authentication."""
        response = await client.delete(
            f"/web-api/v1/projects/{test_project_id}/tags/{test_tag_id}",
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestGBIFSuggestEndpoints:
    """Test GBIF species suggestion endpoints."""

    async def test_gbif_suggest(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/tags/gbif-suggest - returns suggestions list."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/tags/gbif-suggest",
            headers=csrf_headers,
            params={"q": "Parus"},
        )

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)
        # When GBIF API is reachable, verify structure of results
        for item in data:
            assert "key" in item
            assert "canonical_name" in item
            assert "scientific_name" in item
            assert "rank" in item

    async def test_gbif_suggest_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/tags/gbif-suggest requires authentication."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/tags/gbif-suggest",
            params={"q": "Parus"},
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestTagStatisticsEndpoints:
    """Test tag statistics endpoints."""

    async def test_get_statistics(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_tag: Tag,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/tags/statistics - returns list."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/tags/statistics",
            headers=csrf_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)
        # Verify structure of each statistic entry
        for item in data:
            assert "tag" in item
            assert "usage_count" in item
            assert isinstance(item["usage_count"], int)
            tag = item["tag"]
            assert "id" in tag
            assert "name" in tag
            assert "category" in tag

    async def test_get_statistics_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/tags/statistics requires authentication."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/tags/statistics",
        )

        assert response.status_code == 401
