"""Coverage uplift unit tests for ``echoroo.core.pagination``.

Phase 17 §C easy-win batch 1: targets the four uncovered lines (29, 64,
79, 108) in :mod:`echoroo.core.pagination` so the module clears the 85%
threshold without touching production code.

Lines targeted:
    * 29  — :pyattr:`PaginationParams.offset` accessor
    * 64  — fallback branch when ``page_size`` is out of range
    * 79  — :func:`pagination_params_dep` body (FastAPI dep wrapper)
    * 108 — inner ``_dep`` body of :func:`make_pagination_dep`
"""

from __future__ import annotations

import pytest

from echoroo.core.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    PaginationParams,
    make_pagination_dep,
    paginate,
    pagination_params_dep,
)


def test_offset_returns_zero_for_first_page() -> None:
    """``offset`` derives the SQL OFFSET from page / page_size (line 29)."""
    pp = PaginationParams(page=1, page_size=50)
    assert pp.offset == 0


def test_offset_returns_correct_value_for_later_page() -> None:
    """``offset`` jumps by ``page_size`` for each successive page (line 29)."""
    pp = PaginationParams(page=4, page_size=25)
    assert pp.offset == 75


def test_total_pages_returns_one_when_total_zero() -> None:
    """``total_pages`` floors at 1 even with no records."""
    pp = PaginationParams(page=1, page_size=20)
    assert pp.total_pages(0) == 1


def test_total_pages_ceil_division() -> None:
    """``total_pages`` rounds up partial pages."""
    pp = PaginationParams(page=1, page_size=20)
    assert pp.total_pages(45) == 3


@pytest.mark.parametrize("bad_size", [0, -3, MAX_PAGE_SIZE + 1, 9999])
def test_paginate_falls_back_when_page_size_invalid(bad_size: int) -> None:
    """``paginate`` swaps in ``default_page_size`` when ``page_size`` is OOB (line 64)."""
    result = paginate(2, bad_size)
    assert result.page == 2
    assert result.page_size == DEFAULT_PAGE_SIZE


def test_paginate_clamps_page_below_one_to_one() -> None:
    """``paginate`` clamps page < 1 up to 1."""
    result = paginate(-5, 25)
    assert result.page == 1
    assert result.page_size == 25


def test_paginate_keeps_valid_inputs_unchanged() -> None:
    """``paginate`` passes through valid page / page_size values."""
    result = paginate(3, 75)
    assert result.page == 3
    assert result.page_size == 75


def test_pagination_params_dep_returns_validated_params() -> None:
    """The default FastAPI dep wrapper returns a clamped PaginationParams (line 79)."""
    result = pagination_params_dep(page=2, page_size=10)
    assert isinstance(result, PaginationParams)
    assert result.page == 2
    assert result.page_size == 10


def test_pagination_params_dep_uses_module_defaults() -> None:
    """The default FastAPI dep wrapper uses module-wide defaults when called
    with explicit values matching the defaults."""
    result = pagination_params_dep(page=1, page_size=DEFAULT_PAGE_SIZE)
    assert result.page == 1
    assert result.page_size == DEFAULT_PAGE_SIZE


def test_make_pagination_dep_inner_function_returns_params() -> None:
    """The inner ``_dep`` of make_pagination_dep returns clamped params (line 108)."""
    dep = make_pagination_dep(default_page_size=10, max_page_size=20)
    result = dep(page=2, page_size=15)
    assert isinstance(result, PaginationParams)
    assert result.page == 2
    assert result.page_size == 15


def test_make_pagination_dep_uses_supplied_default() -> None:
    """make_pagination_dep honours the supplied ``default_page_size`` for invalid input."""
    dep = make_pagination_dep(default_page_size=7, max_page_size=20)
    # Supply page_size out of bounds via direct call to exercise paginate fallback.
    result = dep(page=1, page_size=99)
    assert result.page_size == 7
