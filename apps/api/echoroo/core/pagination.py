"""Shared pagination utilities for services and routers.

Provides consistent clamping and validation for page/page_size parameters
across all API endpoints, replacing per-service ad-hoc validation.
"""

from dataclasses import dataclass

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class PaginationParams:
    """Validated pagination parameters.

    Ensures page >= 1 and page_size is within [1, max_page_size].
    """

    page: int
    page_size: int

    @property
    def offset(self) -> int:
        """Return the SQL OFFSET value for this page."""
        return (self.page - 1) * self.page_size

    def total_pages(self, total: int) -> int:
        """Return the total number of pages given a record count.

        Returns at least 1 even when total is 0.
        """
        if total <= 0:
            return 1
        return (total + self.page_size - 1) // self.page_size


def paginate(
    page: int,
    page_size: int,
    *,
    default_page_size: int = DEFAULT_PAGE_SIZE,
    max_page_size: int = MAX_PAGE_SIZE,
) -> PaginationParams:
    """Validate and clamp pagination inputs into a :class:`PaginationParams`.

    Args:
        page: Requested page number (1-indexed). Values < 1 are clamped to 1.
        page_size: Requested page size. Values outside [1, max_page_size] fall
            back to *default_page_size*.
        default_page_size: Fallback page size when the requested value is
            invalid. Defaults to :data:`DEFAULT_PAGE_SIZE` (50).
        max_page_size: Upper bound for *page_size*. Defaults to
            :data:`MAX_PAGE_SIZE` (200).

    Returns:
        A :class:`PaginationParams` with normalised values.
    """
    validated_page = max(1, page)
    if page_size < 1 or page_size > max_page_size:
        validated_page_size = default_page_size
    else:
        validated_page_size = page_size
    return PaginationParams(page=validated_page, page_size=validated_page_size)
