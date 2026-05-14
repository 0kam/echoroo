"""Unit checks for H3 resolution validation contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint

from echoroo.models.site import Site
from echoroo.schemas.project import RestrictedConfigUpdateRequest


def _restricted_config_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "allow_media_playback": False,
        "allow_detection_view": False,
        "mask_species_in_detection": False,
        "allow_download": False,
        "allow_export": False,
        "allow_voting_and_comments": False,
        "public_location_precision_h3_res": 3,
        "allow_precise_location_to_viewer": False,
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("resolution", range(3, 16))
def test_restricted_config_accepts_public_location_precision_3_through_15(
    resolution: int,
) -> None:
    payload = _restricted_config_payload(public_location_precision_h3_res=resolution)

    parsed = RestrictedConfigUpdateRequest(**payload)

    assert parsed.public_location_precision_h3_res == resolution


@pytest.mark.parametrize("resolution", [2, 16, "5", True])
def test_restricted_config_rejects_out_of_range_or_non_integer_precision(
    resolution: object,
) -> None:
    payload = _restricted_config_payload(public_location_precision_h3_res=resolution)

    with pytest.raises(ValidationError):
        RestrictedConfigUpdateRequest(**payload)


def test_site_model_check_constraint_allows_h3_member_resolution_5_through_15() -> None:
    constraint = next(
        c
        for c in Site.__table__.constraints
        if isinstance(c, CheckConstraint)
        and c.name == "ck_sites_h3_member_resolution"
    )

    assert str(constraint.sqltext) == "h3_index_member_resolution BETWEEN 5 AND 15"
