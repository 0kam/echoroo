from __future__ import annotations

from fastapi.testclient import TestClient

from echoroo import schemas


def test_lookup_user_requires_auth(client: TestClient) -> None:
    response = client.get(
        "/api/v1/users/lookup/",
        params={"username": "unknown"},
    )
    assert response.status_code == 401


def test_lookup_user_by_username(
    client: TestClient,
    cookies: dict[str, str],
    user: schemas.SimpleUser,
) -> None:
    response = client.get(
        "/api/v1/users/lookup/",
        params={"username": user.username},
        cookies=cookies,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(user.id)
    assert payload["username"] == user.username
