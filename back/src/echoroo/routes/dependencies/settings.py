"""Settings dependencies."""

from typing import Annotated

from fastapi import Depends

from echoroo.system.settings import Settings, get_settings

__all__ = [
    "EchorooSettings",
]


EchorooSettings = Annotated[Settings, Depends(get_settings)]
