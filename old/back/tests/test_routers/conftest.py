import pytest
from fastapi.testclient import TestClient

from echoroo import schemas
from echoroo.system import create_app
from echoroo.system.settings import Settings, get_settings


@pytest.fixture
async def client(settings: Settings):
    """Fixture to initialize the test database."""
    # Create app without lifespan for testing
    # Lifespan includes database initialization which is already done in fixtures
    from fastapi import FastAPI
    from echoroo.system.app.routes import add_routes
    from echoroo.system.app.error_handlers import add_error_handlers
    from echoroo.system.app.middleware import add_middlewares

    app = FastAPI()
    add_routes(app, settings)
    add_error_handlers(app, settings)
    add_middlewares(app, settings)

    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        yield client


@pytest.fixture
def cookies(client: TestClient, user: schemas.SimpleUser) -> dict[str, str]:
    """Fixture to get the cookies from a logged in user."""
    response = client.post(
        "/api/v1/auth/login",
        data={
            "username": user.username,
            "password": "password",
        },
    )

    assert response.status_code == 204
    name, value = response.headers["set-cookie"].split(";")[0].split("=")
    return {name: value}


@pytest.fixture
def superuser_cookies(
    client: TestClient, superuser: schemas.SimpleUser
) -> dict[str, str]:
    """Fixture to get the cookies from a logged in superuser."""
    response = client.post(
        "/api/v1/auth/login",
        data={
            "username": superuser.username,
            "password": "password",
        },
    )

    assert response.status_code == 204
    name, value = response.headers["set-cookie"].split(";")[0].split("=")
    return {name: value}
