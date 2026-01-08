#!/usr/bin/env python3
"""Clear species_cache table to force re-fetching from GBIF API."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "back" / "src"))

from echoroo.models import SpeciesCache
from echoroo.system.database import create_async_db_engine, get_async_session
from echoroo.system.settings import Settings
from sqlalchemy import delete


async def clear_cache(species_names: list[str] | None = None):
    """Clear species cache for specific species or all species.

    Parameters
    ----------
    species_names : list[str] | None
        List of scientific names to clear. If None, clears all cache.
    """
    settings = Settings()
    engine = create_async_db_engine(settings)

    try:
        async for session in get_async_session(engine):
            if species_names:
                # Clear specific species
                stmt = delete(SpeciesCache).where(
                    SpeciesCache.scientific_name.in_(species_names)
                )
                result = await session.execute(stmt)
                await session.commit()

                print(f"✅ Cleared cache for {result.rowcount} species:")
                for name in species_names:
                    print(f"   - {name}")
            else:
                # Clear all cache
                stmt = delete(SpeciesCache)
                result = await session.execute(stmt)
                await session.commit()

                print(f"✅ Cleared all species cache ({result.rowcount} entries)")

    finally:
        await engine.dispose()


if __name__ == "__main__":
    # Problem species that need cache clearing
    problem_species = [
        "Phylloscopus borealoides",
        "Phylloscopus borealis",
        "Poecile montanus",
        "Phylloscopus examinandus",
        "Certhia familiaris",
    ]

    print("=" * 80)
    print("Species Cache Cleaner")
    print("=" * 80)
    print("\nThis will clear the cache for the following species:")
    for name in problem_species:
        print(f"  - {name}")
    print("\nAfter clearing, the next foundation model run will fetch")
    print("fresh data from GBIF API with limit=50.")
    print("=" * 80)

    asyncio.run(clear_cache(problem_species))

    print("\n✅ Done! Run a new foundation model run to fetch updated data.")
