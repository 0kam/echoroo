"""Unit tests for the detections masking key extractor (WS-A v2 slice 4).

:func:`echoroo.api.v1.detections._detection_taxon_key` is the single point
where a detection response is turned into the key that the auto-obscure
pipeline looks up in ``taxon_sensitivities`` / ``project_taxon_sensitivity_
overrides``. Migration 0034 re-keyed those tables onto ``taxa.id``, so this
helper now returns a UUID.

Two safety properties are pinned here:

* the returned key must actually MATCH a sensitivity map keyed by
  ``taxa.id``, including when the tag carries the value as a string;
* a malformed value must raise rather than degrade to ``None``, because
  ``None`` means "unknown taxon" and unknown taxa fail *open*.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from echoroo.api.v1.detections import _detection_taxon_key
from echoroo.core.permissions import (
    H3_RES_5,
    H3_RES_7,
    H3_RES_9,
    H3_RES_15,
    ProjectVisibility,
    compute_effective_resolution,
)


def _detection(tag: object) -> object:
    return SimpleNamespace(tag=tag)


def _public_project() -> object:
    return SimpleNamespace(
        id=uuid4(), visibility=ProjectVisibility.PUBLIC, restricted_config={}
    )


# ---------------------------------------------------------------------------
# Key extraction
# ---------------------------------------------------------------------------


def test_uuid_taxon_id_is_returned_unchanged() -> None:
    taxon_id = uuid4()

    assert _detection_taxon_key(_detection(SimpleNamespace(taxon_id=taxon_id))) == taxon_id


def test_stringified_uuid_is_normalised_to_uuid() -> None:
    """A str-shaped taxon_id must still produce a key that hits the map.

    Response shapes are not all Pydantic (dicts / SimpleNamespace in tests,
    raw rows in some call paths), so the helper coerces rather than trusting
    the declared annotation. Without coercion the lookup below would miss and
    the detection would silently fall back to the open default.
    """
    taxon_id = uuid4()
    tag = SimpleNamespace(taxon_id=str(taxon_id))

    key = _detection_taxon_key(_detection(tag))

    assert isinstance(key, UUID)
    assert key == taxon_id

    # The whole point: the key must match a map keyed by taxa.id.
    sensitivity_map = {taxon_id: H3_RES_5}
    resolution = compute_effective_resolution(
        resource=SimpleNamespace(
            taxon_id=key, h3_index_member_resolution=H3_RES_15
        ),
        role="Guest",
        project=_public_project(),
        taxon_sensitivity_map=sensitivity_map,
    )
    assert resolution == H3_RES_5


def test_uppercase_and_braced_uuid_strings_normalise() -> None:
    """``UUID(str(...))`` accepts the usual textual variants."""
    taxon_id = uuid4()

    for rendering in (str(taxon_id).upper(), f"{{{taxon_id}}}", str(taxon_id).replace("-", "")):
        tag = SimpleNamespace(taxon_id=rendering)
        assert _detection_taxon_key(_detection(tag)) == taxon_id


def test_missing_tag_returns_none() -> None:
    assert _detection_taxon_key(SimpleNamespace(tag=None)) is None
    assert _detection_taxon_key(SimpleNamespace()) is None


def test_tag_without_taxon_returns_none() -> None:
    """A species tag not yet linked to a global taxon has no masking key."""
    assert _detection_taxon_key(_detection(SimpleNamespace(taxon_id=None))) is None


def test_malformed_taxon_id_raises_instead_of_degrading_to_none() -> None:
    """Fail CLOSED: a junk value must error, not silently unmask.

    Returning ``None`` here would classify the detection as "unknown taxon",
    which resolves to H3_RES_9 (open) — i.e. a corrupt value would publish the
    precise location of a potentially sensitive species. Raising surfaces the
    bug as a 500 instead.
    """
    tag = SimpleNamespace(taxon_id="not-a-uuid")

    with pytest.raises(ValueError):
        _detection_taxon_key(_detection(tag))


# ---------------------------------------------------------------------------
# Unknown-taxon default (FR-027) — documented, not changed by this slice
# ---------------------------------------------------------------------------


def test_taxonless_detection_keeps_fr027_open_default() -> None:
    """A detection whose tag has ``taxon_id IS NULL`` stays at H3_RES_9.

    product decision pending: see PR. This slice deliberately does NOT change
    the semantics — a detection with no linked taxon is treated as "no
    sensitivity rule applies" and gets the open default, exactly as before the
    re-key. That is a fail-OPEN default: a genuinely sensitive species whose
    tag was never linked to ``taxa`` is published at full precision. The test
    exists so the behaviour is pinned and visible rather than accidental, and
    so a future decision to fail closed shows up here as a deliberate change.
    """
    resource = SimpleNamespace(taxon_id=None, h3_index_member_resolution=H3_RES_15)

    resolution = compute_effective_resolution(
        resource=resource,
        role="Guest",
        project=_public_project(),
        taxon_sensitivity_map={},
    )

    assert resolution == H3_RES_9


def test_taxonless_detection_under_iucn_fail_safe_keeps_h3_res_7() -> None:
    """Under the FR-036 fail-safe the unknown-taxon default coarsens to 7.

    product decision pending: see PR. Same caveat as the test above — this
    pins today's behaviour. ``bulk_load_sensitivity_map`` only pre-populates
    the fail-safe default for taxa it was ASKED about, and a taxonless
    detection is never in that set, so the coarsening below only applies once
    a taxon id exists. Recorded here so the asymmetry is explicit.
    """
    taxon_id = uuid4()
    resource = SimpleNamespace(
        taxon_id=taxon_id, h3_index_member_resolution=H3_RES_15
    )

    resolution = compute_effective_resolution(
        resource=resource,
        role="Guest",
        project=_public_project(),
        # What bulk_load_sensitivity_map returns for an unknown taxon while
        # the IUCN fail-safe is active.
        taxon_sensitivity_map={taxon_id: H3_RES_7},
    )

    assert resolution == H3_RES_7
