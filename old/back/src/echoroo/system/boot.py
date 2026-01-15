import webbrowser

from colorama import Fore, Style, just_fix_windows_console
from sqlalchemy import select

from echoroo import models
from echoroo.system.database import (
    create_async_db_engine,
    get_async_session,
    get_database_url,
    init_database,
)
from echoroo.system.settings import Settings
from echoroo.system.users import is_first_user

just_fix_windows_console()


def print_ready_message(settings: Settings):
    host = settings.host
    port = settings.port

    print(
        f"""
    {Fore.GREEN}{Style.DIM}Echoroo is ready to go!{Style.RESET_ALL}

    {Fore.GREEN}{Style.BRIGHT} * Listening on http://{host}:{port}/{Style.RESET_ALL}

    {Fore.YELLOW}Press Ctrl+C to exit.{Style.RESET_ALL}
    """
    )


def print_first_run_message(settings: Settings):
    host = settings.host
    port = settings.port

    print(
        f"""
    {Fore.YELLOW}{Style.BRIGHT}This is the first time you run Echoroo, welcome!{Style.RESET_ALL}

    {Fore.GREEN}{Style.DIM}Echoroo is ready to go!{Style.RESET_ALL}

    {Fore.GREEN}{Style.BRIGHT} * Navigate to http://{host}:{port}/first to create your first user.{Style.RESET_ALL}

    {Fore.YELLOW}Press Ctrl+C to exit.{Style.RESET_ALL}
    """
    )


async def is_first_run(settings: Settings) -> bool:
    """Check if this is the first time the application is run."""
    db_url = get_database_url(settings)
    engine = create_async_db_engine(db_url)
    async with get_async_session(engine) as session:
        is_first_run = await is_first_user(session)

    return is_first_run


def print_dev_message(settings: Settings):
    database_url = get_database_url(settings)
    settings_str = settings.model_dump_json(
        indent=4,
        exclude={"db_username", "db_password", "db_url"},
    )
    print(
        f"""
{Fore.RED}{Style.BRIGHT}Echoroo is running in development mode!{Style.RESET_ALL}

{Fore.GREEN}{Style.BRIGHT}Database URL:{Style.RESET_ALL} {database_url}

{Fore.GREEN}{Style.BRIGHT}Settings:{Style.RESET_ALL} {settings_str}
    """
    )


def is_dev_mode(settings: Settings) -> bool:
    """Check if the application is running in development mode."""
    return settings.dev


def open_echoroo_on_browser(settings: Settings) -> None:
    """Open Echoroo in the browser using the configured domain."""
    # Use domain instead of host for browser opening
    # host might be 0.0.0.0 which is not accessible from browser
    webbrowser.open(f"http://{settings.domain}:{settings.port}/")


async def echoroo_init(settings: Settings):
    """Run at initialization."""
    if is_dev_mode(settings):
        print_dev_message(settings)

    await init_database(settings)

    # Warm up database session and access tokens table to prevent auth issues
    # on first request after restart
    db_url = get_database_url(settings)
    engine = create_async_db_engine(db_url)
    async with get_async_session(engine) as session:
        # Query access tokens table to ensure it's fully initialized
        # This prevents authentication issues on the first login attempt
        await session.execute(select(models.AccessToken).limit(1))
        await session.commit()
    await engine.dispose()

    if await is_first_run(settings):
        print_first_run_message(settings)

        if settings.open_on_startup:
            open_echoroo_on_browser(settings)
        return

    print_ready_message(settings)

    if settings.open_on_startup:
        open_echoroo_on_browser(settings)
