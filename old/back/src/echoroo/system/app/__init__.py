import functools

from fastapi import FastAPI

from echoroo.system.app.error_handlers import add_error_handlers
from echoroo.system.app.lifespan import lifespan
from echoroo.system.app.middleware import add_middlewares
from echoroo.system.app.routes import ROOT_DIR, add_routes
from echoroo.system.settings import Settings

__all__ = ["create_app", "ROOT_DIR"]


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(lifespan=functools.partial(lifespan, settings))
    add_routes(app, settings)
    add_error_handlers(app, settings)
    add_middlewares(app, settings)
    return app
