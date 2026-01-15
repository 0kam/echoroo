"""Search result filter builder service."""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import ColumnExpressionArgument

from echoroo import models

if TYPE_CHECKING:
    pass

__all__ = ["SearchResultFilterBuilder"]


class SearchResultFilterBuilder:
    """Builder for constructing SearchResult query filters."""

    @staticmethod
    def build_filters(
        search_session_id: int,
        is_labeled: bool | None = None,
        assigned_tag_ids: list[int] | None = None,
        is_negative: bool | None = None,
        is_uncertain: bool | None = None,
        is_skipped: bool | None = None,
        sample_type: str | None = None,
        iteration_added: int | None = None,
    ) -> list[ColumnExpressionArgument[bool]]:
        """Build list of WHERE clause filters for SearchResult queries.

        Args:
            search_session_id: Search session database ID (required)
            is_labeled: Filter by labeled/unlabeled status
            assigned_tag_ids: Filter by assigned tag IDs (multi-label support)
            is_negative: Filter by negative label
            is_uncertain: Filter by uncertain label
            is_skipped: Filter by skipped label
            sample_type: Filter by sample type
            iteration_added: Filter by iteration number

        Returns:
            List of SQLAlchemy filter expressions
        """
        filters: list[ColumnExpressionArgument[bool]] = []

        # Labeled filter (includes tags, negative, uncertain, or skipped)
        if is_labeled is not None:
            filters.extend(
                SearchResultFilterBuilder._build_labeled_filter(is_labeled)
            )

        # Boolean label filters
        if is_negative is not None:
            filters.append(models.SearchResult.is_negative == is_negative)

        if is_uncertain is not None:
            filters.append(models.SearchResult.is_uncertain == is_uncertain)

        if is_skipped is not None:
            filters.append(models.SearchResult.is_skipped == is_skipped)

        # Tag filter
        if assigned_tag_ids is not None:
            filters.append(
                SearchResultFilterBuilder._build_tag_filter(assigned_tag_ids)
            )

        # Sample type filter
        if sample_type is not None:
            filters.append(models.SearchResult.sample_type == sample_type)

        # Iteration filter
        if iteration_added is not None:
            filters.append(models.SearchResult.iteration_added == iteration_added)

        return filters

    @staticmethod
    def _build_labeled_filter(
        is_labeled: bool,
    ) -> list[ColumnExpressionArgument[bool]]:
        """Build filter for labeled/unlabeled status.

        A result is considered "labeled" if it has:
        - Any assigned tags (via junction table)
        - OR is_negative flag set
        - OR is_uncertain flag set
        - OR is_skipped flag set

        Args:
            is_labeled: True for labeled, False for unlabeled

        Returns:
            List of filter expressions
        """
        from sqlalchemy import exists, or_, select

        has_tags = exists(
            select(1).where(
                models.SearchResultTag.search_result_id == models.SearchResult.id
            )
        )

        if is_labeled:
            # Labeled: has tags OR has any boolean flag
            return [
                or_(
                    has_tags,
                    models.SearchResult.is_negative == True,
                    models.SearchResult.is_uncertain == True,
                    models.SearchResult.is_skipped == True,
                )
            ]
        else:
            # Unlabeled: no tags AND all boolean flags are False
            return [
                ~has_tags,
                models.SearchResult.is_negative == False,
                models.SearchResult.is_uncertain == False,
                models.SearchResult.is_skipped == False,
            ]

    @staticmethod
    def _build_tag_filter(
        assigned_tag_ids: list[int],
    ) -> ColumnExpressionArgument[bool]:
        """Build filter for assigned tags.

        Filters results that have ANY of the specified tags
        (multi-label OR behavior).

        Args:
            assigned_tag_ids: List of tag IDs to filter by

        Returns:
            Filter expression using EXISTS subquery
        """
        from sqlalchemy import exists, select

        has_any_tag = exists(
            select(1).where(
                models.SearchResultTag.search_result_id == models.SearchResult.id,
                models.SearchResultTag.tag_id.in_(assigned_tag_ids),
            )
        )
        return has_any_tag
