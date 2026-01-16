"""H3 utility functions for geospatial operations."""

import h3


def validate_h3_index(h3_index: str) -> tuple[bool, int | None, str | None]:
    """Validate an H3 index.

    Args:
        h3_index: H3 cell index to validate

    Returns:
        Tuple of (is_valid, resolution, error_message)
    """
    try:
        if not h3.is_valid_cell(h3_index):
            return False, None, "Invalid H3 index format"

        resolution = h3.get_resolution(h3_index)
        if resolution < 5 or resolution > 15:
            return False, resolution, f"Resolution {resolution} out of range (5-15)"

        return True, resolution, None
    except Exception as e:
        return False, None, str(e)


def h3_from_coordinates(latitude: float, longitude: float, resolution: int) -> str:
    """Get H3 index from latitude/longitude coordinates.

    Args:
        latitude: Latitude in decimal degrees
        longitude: Longitude in decimal degrees
        resolution: H3 resolution (5-15)

    Returns:
        H3 cell index

    Raises:
        ValueError: If coordinates or resolution are invalid
    """
    if not (-90 <= latitude <= 90):
        raise ValueError("Latitude must be between -90 and 90")
    if not (-180 <= longitude <= 180):
        raise ValueError("Longitude must be between -180 and 180")
    if not (5 <= resolution <= 15):
        raise ValueError("Resolution must be between 5 and 15")

    result: str = h3.latlng_to_cell(latitude, longitude, resolution)
    return result


def h3_to_center(h3_index: str) -> tuple[float, float]:
    """Get center coordinates of an H3 cell.

    Args:
        h3_index: H3 cell index

    Returns:
        Tuple of (latitude, longitude)
    """
    lat, lng = h3.cell_to_latlng(h3_index)
    return lat, lng


def h3_to_boundary(h3_index: str) -> list[list[float]]:
    """Get boundary coordinates of an H3 cell.

    Args:
        h3_index: H3 cell index

    Returns:
        List of [latitude, longitude] coordinate pairs
    """
    boundary = h3.cell_to_boundary(h3_index)
    return [[lat, lng] for lat, lng in boundary]


def h3_get_resolution(h3_index: str) -> int:
    """Get the resolution of an H3 index.

    Args:
        h3_index: H3 cell index

    Returns:
        Resolution (0-15)
    """
    result: int = h3.get_resolution(h3_index)
    return result


def h3_coordinate_uncertainty(h3_index: str) -> float:
    """Estimate coordinate uncertainty based on H3 resolution.

    Returns approximate edge length in meters.

    Args:
        h3_index: H3 cell index

    Returns:
        Coordinate uncertainty in meters
    """
    resolution = h3.get_resolution(h3_index)
    # Approximate edge lengths by resolution (from H3 documentation)
    edge_lengths = {
        0: 1107712.59,
        1: 418676.01,
        2: 158244.66,
        3: 59810.86,
        4: 22606.38,
        5: 8544.41,
        6: 3229.48,
        7: 1220.63,
        8: 461.35,
        9: 174.38,
        10: 65.91,
        11: 24.91,
        12: 9.42,
        13: 3.56,
        14: 1.35,
        15: 0.51,
    }
    return edge_lengths.get(resolution, 0.0)
