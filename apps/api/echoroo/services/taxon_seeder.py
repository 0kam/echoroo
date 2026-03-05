"""BirdNET taxa seeder — populates the taxa table from the BirdNET species list."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.repositories.taxon import TaxonRepository

logger = logging.getLogger(__name__)

# BirdNET common names that represent non-biological sound sources.
# These are matched against the common-name portion of each BirdNET label.
_NON_BIOLOGICAL_COMMON_NAMES: frozenset[str] = frozenset(
    {
        "Dog",
        "Engine",
        "Environmental",
        "Fireworks",
        "Gun",
        "Human non-vocal",
        "Human vocal",
        "Human whistle",
        "Noise",
        "Power tools",
        "Siren",
    }
)


def _parse_birdnet_label(label: str) -> tuple[str, str]:
    """Parse a BirdNET species-list label into (scientific_name, common_name).

    BirdNET labels use the format "Genus_species_Common Name" where the
    scientific name components are joined with underscores and the common
    name follows the final underscore.  The split is performed on the first
    underscore that separates the *scientific* part from the common-name
    part.  Because scientific names contain exactly one underscore
    ("Genus_species"), we split on the first underscore to get genus, then
    split the remainder on the next underscore to separate species from the
    common name.

    For labels that do not follow the two-underscore pattern we fall back
    to a simple split-on-first-underscore so the function is robust against
    edge cases.

    Args:
        label: Raw BirdNET species-list entry, e.g.
               ``"Turdus_merula_Eurasian Blackbird"``.

    Returns:
        Tuple of (scientific_name, common_name) where scientific_name uses
        a space between genus and species (e.g. ``"Turdus merula"``) and
        common_name is the human-readable label (e.g.
        ``"Eurasian Blackbird"``).
    """
    # Expected format: "<Genus>_<species>_<Common Name with spaces>"
    parts = label.split("_", 2)
    if len(parts) == 3:
        # parts[0]=Genus, parts[1]=species, parts[2]=Common Name
        scientific_name = f"{parts[0]} {parts[1]}"
        common_name = parts[2]
    elif len(parts) == 2:
        # e.g. "SomeLabel_Common Name" — treat first part as scientific name
        scientific_name = parts[0]
        common_name = parts[1]
    else:
        # No underscore; treat the whole label as scientific name
        scientific_name = label
        common_name = ""

    return scientific_name.strip(), common_name.strip()


def _get_birdnet_species_list() -> list[str]:
    """Return the BirdNET species list without loading the full ML model.

    The birdnet package ships a plain-text labels file that can be read
    directly, avoiding the heavy TensorFlow/TFLite model initialisation.
    If the file cannot be located we fall back to instantiating a minimal
    BirdNETWrapper (which loads the model) so that seeding still works even
    in non-standard package layouts.

    Returns:
        List of raw label strings in BirdNET format.
    """
    import importlib.util
    from pathlib import Path

    # Try to find the labels file shipped with the birdnet package.
    spec = importlib.util.find_spec("birdnet")
    if spec is not None and spec.origin is not None:
        package_dir = Path(spec.origin).parent
        # Common relative paths used by different birdnet package versions
        candidate_paths = [
            package_dir / "checkpoints" / "V2.4" / "BirdNET_GLOBAL_6K_V2.4_Labels.txt",
            package_dir / "checkpoints" / "V2.4" / "labels.txt",
            package_dir / "labels" / "V2.4" / "BirdNET_GLOBAL_6K_V2.4_Labels.txt",
        ]
        for path in candidate_paths:
            if path.exists():
                logger.info("Reading BirdNET labels from %s", path)
                return [line.strip() for line in path.read_text().splitlines() if line.strip()]

        # Walk the package directory for any .txt file that looks like a labels file
        for txt_file in sorted(package_dir.rglob("*Labels*.txt")):
            logger.info("Reading BirdNET labels from %s (glob match)", txt_file)
            return [line.strip() for line in txt_file.read_text().splitlines() if line.strip()]

    # Fall back to loading the model and reading its species_list attribute
    logger.warning(
        "BirdNET labels file not found — falling back to model load (slower)"
    )
    from echoroo.ml.birdnet_wrapper import BirdNETWrapper

    wrapper = BirdNETWrapper.get_instance(device="CPU")
    wrapper.load()
    # species_list is populated by load()
    species_list: list[str] = wrapper._species_list or []  # noqa: SLF001
    return species_list


async def seed_birdnet_taxa(db: AsyncSession) -> int:
    """Seed taxa from the BirdNET species list.

    Reads the BirdNET species list (from the labels file shipped with the
    package or, as a fallback, by loading the ML model), parses each entry,
    and inserts any taxa not already present in the database.

    The operation is idempotent — re-running on a populated database safely
    skips existing taxa.

    Args:
        db: Async SQLAlchemy session.  The caller is responsible for
            committing the transaction after this function returns.

    Returns:
        Number of newly created taxa.
    """
    species_list = _get_birdnet_species_list()
    if not species_list:
        logger.error("BirdNET species list is empty — seeding aborted")
        return 0

    logger.info("Seeding taxa from BirdNET species list (%d entries)", len(species_list))

    taxa_data: list[dict[str, object]] = []
    for label in species_list:
        scientific_name, common_name = _parse_birdnet_label(label)
        if not scientific_name:
            continue
        is_non_biological = common_name in _NON_BIOLOGICAL_COMMON_NAMES
        taxa_data.append(
            {
                "scientific_name": scientific_name,
                "common_name": common_name or None,
                "is_non_biological": is_non_biological,
            }
        )

    repo = TaxonRepository(db)
    created = await repo.bulk_create(taxa_data)

    logger.info(
        "BirdNET taxa seeding complete: %d new taxa created out of %d labels",
        created,
        len(species_list),
    )
    return created
