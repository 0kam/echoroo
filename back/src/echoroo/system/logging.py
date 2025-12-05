import json
from typing import Any

from uvicorn.config import LOGGING_CONFIG

from echoroo.system.data import get_app_data_dir
from echoroo.system.settings import Settings


def get_logging_config(settings: Settings) -> dict[str, Any]:
    """Get the logging configuration.

    Will create the logging configuration file if it does not exist,
    otherwise it will read the configuration from the file.

    Parameters
    ----------
    settings: Settings
        The application settings.

    Returns
    -------
    dict[str, Any]
        The logging configuration.
    """
    if settings.dev:
        return generate_dev_logging_config()

    data_dir = get_app_data_dir()
    log_config_file = data_dir / settings.log_config

    if not log_config_file.exists():
        config = generate_logging_config(settings)
        log_config_file.write_text(json.dumps(config, indent=4))

    return json.loads(log_config_file.read_text())


def generate_dev_logging_config():
    """Generate the logging configuration for development.

    Returns
    -------
    dict[str, Any]
        The logging configuration.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            **LOGGING_CONFIG["formatters"],
            "echoroo": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "echoroo",
                "stream": "ext://sys.stdout",
            },
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "access",
                "stream": "ext://sys.stdout",
            },
            "console.error": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stderr",
            },
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["default", "console"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["default", "console.error"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
            "echoroo": {
                "handlers": ["default", "console"],
                "level": "DEBUG",
                "propagate": False,
            },
        },
    }


def generate_logging_config(settings: Settings) -> dict[str, Any]:
    """Generate the logging configuration.

    Parameters
    ----------
    settings: Settings
        The application settings.

    Returns
    -------
    dict[str, Any]
        The logging configuration.
    """
    data_dir = get_app_data_dir()
    log_dir = data_dir / settings.log_dir
    echoroo_log_file = log_dir / "echoroo.log"
    access_log_file = log_dir / "access.log"
    error_log_file = log_dir / "error.log"

    if settings.log_to_file:
        log_dir.mkdir(parents=True, exist_ok=True)
        echoroo_log_file.touch(exist_ok=True)
        access_log_file.touch(exist_ok=True)
        error_log_file.touch(exist_ok=True)

    file_handlers = {
        "error": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "default",
            "filename": str(error_log_file),
            "backupCount": 10,
            "maxBytes": 2 * 1024 * 1024,
        },
        "access": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "access",
            "filename": str(access_log_file),
            "backupCount": 10,
            "maxBytes": 2 * 1024 * 1024,
        },
        "default": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "echoroo",
            "filename": str(echoroo_log_file),
            "backupCount": 10,
            "maxBytes": 2 * 1024 * 1024,
        },
    }

    console_handlers = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "access",
            "stream": "ext://sys.stdout",
        },
        "console.error": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stderr",
        },
    }

    handlers = {}
    if settings.log_to_file:
        handlers.update(file_handlers)

    if settings.log_to_stdout:
        handlers.update(console_handlers)

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            **LOGGING_CONFIG["formatters"],
            "echoroo": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            },
        },
        "handlers": handlers,
        "loggers": {
            "uvicorn": {
                "handlers": _get_handlers("default", "console", settings),
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": _get_handlers("error", "console.error", settings),
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": _get_handlers("access", "console", settings),
                "level": "INFO",
                "propagate": False,
            },
            "echoroo": {
                "handlers": _get_handlers("default", "console", settings),
                "level": settings.log_level.upper(),
                "propagate": False,
            },
        },
    }


def _get_handlers(
    file_handler: str,
    console_handler: str,
    settings: Settings,
) -> list[str]:
    if settings.log_to_file and settings.log_to_stdout:
        return [file_handler, console_handler]

    if settings.log_to_file:
        return [file_handler]

    if settings.log_to_stdout:
        return [console_handler]

    return []
