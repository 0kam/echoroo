"""Main entry point for echoroo.

This module is used to run the app using uvicorn.
"""

import uvicorn

from echoroo.system import get_logging_config, get_settings


def main():
    settings = get_settings()
    config = get_logging_config(settings)
    uvicorn.run(
        "echoroo.app:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=settings.dev,
        log_config=config,
    )


if __name__ == "__main__":
    main()
