"""Test suite for the Tags endpoints."""

from fastapi.testclient import TestClient

from echoroo import schemas


async def test_create_tag_returns_existing_tag_if_duplicate(
    client: TestClient,
    tag: schemas.Tag,
    cookies: dict[str, str],
):
    response = client.post(
        "/api/v1/tags/",
        json={
            "key": tag.key,
            "value": tag.value,
            "canonical_name": tag.canonical_name,
        },
        cookies=cookies,
    )

    assert response.status_code == 200
    content = response.json()

    assert content["key"] == tag.key
    assert content["value"] == tag.value
    assert content["canonical_name"] == tag.canonical_name

    # And do it again for good measure
    response = client.post(
        "/api/v1/tags/",
        json={
            "key": tag.key,
            "value": tag.value,
            "canonical_name": tag.canonical_name,
        },
        cookies=cookies,
    )
    assert response.status_code == 200


async def test_create_tag_rejects_non_species_key(
    client: TestClient,
    cookies: dict[str, str],
):
    response = client.post(
        "/api/v1/tags/",
        json={
            "key": "not_species",
            "value": "12345",
            "canonical_name": "Invalid key",
        },
        cookies=cookies,
    )

    assert response.status_code == 422
    assert "species" in response.json()["detail"]


async def test_create_tag_rejects_non_numeric_value(
    client: TestClient,
    cookies: dict[str, str],
):
    response = client.post(
        "/api/v1/tags/",
        json={
            "key": "species",
            "value": "not-a-usage-key",
            "canonical_name": "Invalid usageKey",
        },
        cookies=cookies,
    )

    assert response.status_code == 422
    assert "usageKey" in response.json()["detail"]
