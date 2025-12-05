"""Functions to handle images."""

from io import BytesIO

import numpy as np
from matplotlib import colormaps
from PIL import Image as img
from PIL.Image import Image

__all__ = [
    "array_to_image",
    "image_to_buffer",
]


def array_to_image(
    array: np.ndarray,
    cmap: str,
    resize: tuple[int, int] | None = None,
    resample: int = img.Resampling.LANCZOS,
) -> Image:
    """Convert a numpy array to a PIL image.

    Parameters
    ----------
    array : np.ndarray
        The array to convert into an image. It must be a 2D array.
    cmap : str
        The colormap to use.
    resize : tuple[int, int] | None
        Optional target size (width, height) to resize the image to.
        If None, uses the original array size.
    resample : int
        Resampling filter to use for resizing. Default is LANCZOS for high quality.

    Returns
    -------
    Image
        A Pillow Image object.

    Notes
    -----
    The array values must be between 0 and 1.
    """
    if array.ndim != 2:
        raise ValueError("The array must be 2D.")

    # Get the colormap
    colormap = colormaps.get_cmap(cmap)

    # Flip the array vertically
    array = np.flipud(array)

    # Convert to image
    image = img.fromarray(np.uint8(colormap(array) * 255))

    # Resize if requested
    if resize is not None:
        width, height = resize
        image = image.resize((width, height), resample=resample)

    return image


def image_to_buffer(image: Image, fmt: str = "png") -> BytesIO:
    """Convert a PIL image to a BytesIO buffer."""
    buffer = BytesIO()
    image.save(buffer, format=fmt)
    buffer.seek(0)
    return buffer
