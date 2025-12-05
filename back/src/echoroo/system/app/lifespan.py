from contextlib import asynccontextmanager

from fastapi import FastAPI

from echoroo.system.boot import echoroo_init
from echoroo.system.settings import Settings

__all__ = ["lifespan"]


@asynccontextmanager
async def lifespan(settings: Settings, _: FastAPI):
    """Context manager to run startup and shutdown events."""
    await echoroo_init(settings)

    yield
