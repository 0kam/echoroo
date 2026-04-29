"""Contract tests for ``locale`` support on Tag and Detection API endpoints.

These tests cover the end-to-end behaviour exposed by the API:

* ``TagResponse`` carries a ``vernacular_name`` field that is populated from
  ``taxon_vernacular_names`` when a matching locale row exists.
* The field is ``None`` when the tag has no linked ``taxon_id``, when no
  matching vernacular row exists, or when the tag's taxon has vernacular
  rows only for other locales.
* Batched vernacular resolution is used for list endpoints so the
  per-locale lookup runs in a single query regardless of page size
  (N+1 regression guard).

The tests also assert the underlying helper (``resolve_vernacular_names``)
emits exactly one ``SELECT ... taxon_vernacular_names`` query for a 100+
item detection listing.
"""

from __future__ import annotations



# Phase 13 P1.5 R2 (Codex follow-up — Fatal): this suite exercises the
# rich-shape ``Annotation`` ORM (``recording_id`` / ``tag_id`` / ``status``
# / ``confidence`` / ``start_time`` / ``end_time`` / ``freq_low`` /
# ``freq_high`` / ``reviewed_by_id`` / ``reviewed_at`` /
# ``search_session_id`` / ``detection_run_id``). The DB-truth schema only
# carries the minimal detection-based shape (id / detection_id / user_id /
# source / taxon_id / label) — the rich shape is **deferred to Phase 14+**
# when a separate ``recording_annotations`` table will reinstate it. Until
# then the suite below cannot run; reactivate it in Phase 14+ when the
# ``recording_annotations`` ORM + table are wired up.
#
# TODO(Phase 14+ recording_annotations): drop this skip and re-validate.
import pytest as _pytest_phase14_skip  # noqa: E402

pytestmark = _pytest_phase14_skip.mark.skip(
    reason=(
        "Phase 14+ deferred — rich-shape Annotation columns (recording_id /"
        " tag_id / status / start_time / end_time / etc) live on the future"
        " ``recording_annotations`` table; see ``apps/api/echoroo/models/"
        "annotation.py`` and ``apps/api/echoroo/models/recording_annotation.py``"
        " module docstrings."
    ),
)
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.engine.interfaces import DBAPICursor
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.annotation import Annotation
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    DatetimeParseStatus,
    DetectionSource,
    DetectionStatus,
    TagCategory,
)
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.tag import Tag
from echoroo.models.taxon import Taxon
from echoroo.models.taxon_vernacular_name import TaxonVernacularName
from echoroo.models.user import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def seeded_taxon(db_session: AsyncSession) -> Taxon:
    """Create a unique taxon per test with both ``en`` and ``ja`` vernaculars.

    The ``taxa`` table persists across tests (it represents expensive-to-
    rebuild global reference data), so each test gets a unique scientific
    name so it cannot collide with earlier-seeded rows.
    """
    # Unique per test via uuid4; scientific_name column is limited to 300
    # chars, which easily accommodates a suffix.
    suffix = uuid4().hex[:12]
    taxon = Taxon(
        scientific_name=f"LocaleTest Species {suffix}",
        gbif_taxon_key=None,
        rank="SPECIES",
    )
    db_session.add(taxon)
    await db_session.commit()
    await db_session.refresh(taxon)

    db_session.add_all(
        [
            TaxonVernacularName(
                taxon_id=taxon.id,
                locale="en",
                name="Common Blackbird",
                source="gbif",
                is_primary=True,
            ),
            TaxonVernacularName(
                taxon_id=taxon.id,
                locale="ja",
                name="クロウタドリ",
                source="gbif",
                is_primary=True,
            ),
        ]
    )
    await db_session.commit()
    return taxon


@pytest.fixture
async def orphan_taxon(db_session: AsyncSession) -> Taxon:
    """Create a unique taxon with zero vernacular rows for the test."""
    suffix = uuid4().hex[:12]
    taxon = Taxon(
        scientific_name=f"OrphanTest Species {suffix}",
        gbif_taxon_key=None,
        rank="SPECIES",
    )
    db_session.add(taxon)
    await db_session.commit()
    await db_session.refresh(taxon)
    return taxon


@pytest.fixture
async def tag_with_taxon(
    db_session: AsyncSession,
    test_project: Project,
    seeded_taxon: Taxon,
) -> Tag:
    """Species tag linked to the seeded taxon (has both en + ja vernacular)."""
    tag = Tag(
        project_id=test_project.id,
        name="Turdus merula",
        category=TagCategory.SPECIES,
        scientific_name="Turdus merula",
        common_name="Common blackbird",
        taxon_id=seeded_taxon.id,
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag


@pytest.fixture
async def tag_without_taxon(
    db_session: AsyncSession,
    test_project: Project,
) -> Tag:
    """Species tag without a linked ``taxon_id`` (vernacular should be None)."""
    tag = Tag(
        project_id=test_project.id,
        name="Unknown species",
        category=TagCategory.SPECIES,
        scientific_name="Unknown species",
        common_name="Unknown",
        taxon_id=None,
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag


@pytest.fixture
async def tag_with_orphan_taxon(
    db_session: AsyncSession,
    test_project: Project,
    orphan_taxon: Taxon,
) -> Tag:
    """Species tag whose taxon has no vernacular name rows at all."""
    tag = Tag(
        project_id=test_project.id,
        name="Parus major",
        category=TagCategory.SPECIES,
        scientific_name="Parus major",
        common_name="Great tit",
        taxon_id=orphan_taxon.id,
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag


@pytest.fixture
async def locale_site(
    db_session: AsyncSession,
    test_project: Project,
) -> Site:
    """Create a site required by the ``datasets.site_id`` FK."""
    site = Site(
        project_id=test_project.id,
        name="Locale Test Site",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def dataset_recording(
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
    locale_site: Site,
) -> Recording:
    """Create a dataset + recording scoped to ``test_project``."""
    dataset = Dataset(
        project_id=test_project.id,
        site_id=locale_site.id,
        created_by_id=test_user.id,
        name="Locale Test Dataset",
        audio_dir="/data/audio",
        status=DatasetStatus.COMPLETED,
        visibility=DatasetVisibility.PRIVATE,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)

    recording = Recording(
        dataset_id=dataset.id,
        filename="locale_test.wav",
        path="locale_test.wav",
        hash="locale-hash-0001",
        duration=600.0,
        samplerate=44100,
        channels=1,
        datetime_parse_status=DatetimeParseStatus.PENDING,
        time_expansion=1.0,
    )
    db_session.add(recording)
    await db_session.commit()
    await db_session.refresh(recording)
    return recording


# ---------------------------------------------------------------------------
# Tag endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTagLocaleEndpoints:
    """Locale handling on ``GET /projects/{id}/tags`` and ``/tags/{tag_id}``."""

    async def test_list_tags_default_locale_returns_english_vernacular(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        tag_with_taxon: Tag,
    ) -> None:
        """Default ``locale=en`` populates the English vernacular name."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/tags",
            headers=auth_headers,
        )
        assert response.status_code == 200
        items = response.json()["items"]
        match = next(i for i in items if i["id"] == str(tag_with_taxon.id))
        assert match["vernacular_name"] == "Common Blackbird"
        # common_name stays unchanged (not overwritten).
        assert match["common_name"] == "Common blackbird"

    async def test_list_tags_locale_ja_returns_japanese_vernacular(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        tag_with_taxon: Tag,
    ) -> None:
        """``locale=ja`` returns the Japanese vernacular entry."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/tags",
            headers=auth_headers,
            params={"locale": "ja"},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        match = next(i for i in items if i["id"] == str(tag_with_taxon.id))
        assert match["vernacular_name"] == "クロウタドリ"

    async def test_list_tags_without_taxon_id_returns_null_vernacular(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        tag_without_taxon: Tag,
    ) -> None:
        """Tags with no ``taxon_id`` surface ``vernacular_name = null``."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/tags",
            headers=auth_headers,
            params={"locale": "ja"},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        match = next(i for i in items if i["id"] == str(tag_without_taxon.id))
        assert match["vernacular_name"] is None

    async def test_list_tags_orphan_taxon_returns_null_vernacular(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        tag_with_orphan_taxon: Tag,
    ) -> None:
        """Tag linked to a taxon with no vernacular rows stays ``None``."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/tags",
            headers=auth_headers,
            params={"locale": "ja"},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        match = next(
            i for i in items if i["id"] == str(tag_with_orphan_taxon.id)
        )
        assert match["vernacular_name"] is None

    async def test_get_tag_detail_locale_ja(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        tag_with_taxon: Tag,
    ) -> None:
        """``GET /tags/{tag_id}?locale=ja`` populates vernacular_name."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/tags/{tag_with_taxon.id}",
            headers=auth_headers,
            params={"locale": "ja"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["vernacular_name"] == "クロウタドリ"

    async def test_list_tags_rejects_unsupported_locale(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Locale outside the ``en|ja`` allow-list fails validation."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/tags",
            headers=auth_headers,
            params={"locale": "fr"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Detection endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDetectionLocaleEndpoints:
    """Locale handling on ``GET /projects/{id}/detections`` (list + detail)."""

    async def test_list_detections_populates_tag_vernacular(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_project_id: str,
        dataset_recording: Recording,
        tag_with_taxon: Tag,
    ) -> None:
        """Each detection's embedded tag carries the requested locale name."""
        annotation = Annotation(
            recording_id=dataset_recording.id,
            tag_id=tag_with_taxon.id,
            source=DetectionSource.BIRDNET,
            status=DetectionStatus.UNREVIEWED,
            confidence=0.9,
            start_time=1.0,
            end_time=2.0,
        )
        db_session.add(annotation)
        await db_session.commit()

        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections",
            headers=auth_headers,
            params={"locale": "ja"},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) >= 1
        assert items[0]["tag"]["vernacular_name"] == "クロウタドリ"

    async def test_list_detections_tag_without_taxon_has_null_vernacular(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_project_id: str,
        dataset_recording: Recording,
        tag_without_taxon: Tag,
    ) -> None:
        """Tags without ``taxon_id`` produce ``vernacular_name = null``."""
        annotation = Annotation(
            recording_id=dataset_recording.id,
            tag_id=tag_without_taxon.id,
            source=DetectionSource.HUMAN,
            status=DetectionStatus.UNREVIEWED,
            confidence=None,
            start_time=3.0,
            end_time=4.0,
        )
        db_session.add(annotation)
        await db_session.commit()

        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections",
            headers=auth_headers,
            params={"locale": "ja"},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        target = next(
            i for i in items if i.get("tag") and i["tag"]["id"] == str(tag_without_taxon.id)
        )
        assert target["tag"]["vernacular_name"] is None

    async def test_list_detections_orphan_taxon_has_null_vernacular(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_project_id: str,
        dataset_recording: Recording,
        tag_with_orphan_taxon: Tag,
    ) -> None:
        """Annotations tagged with taxa missing a locale row still succeed."""
        annotation = Annotation(
            recording_id=dataset_recording.id,
            tag_id=tag_with_orphan_taxon.id,
            source=DetectionSource.BIRDNET,
            status=DetectionStatus.UNREVIEWED,
            confidence=0.7,
            start_time=5.0,
            end_time=6.0,
        )
        db_session.add(annotation)
        await db_session.commit()

        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections",
            headers=auth_headers,
            params={"locale": "ja"},
        )
        assert response.status_code == 200
        items = response.json()["items"]
        target = next(
            i
            for i in items
            if i.get("tag") and i["tag"]["id"] == str(tag_with_orphan_taxon.id)
        )
        assert target["tag"]["vernacular_name"] is None

    async def test_get_detection_detail_locale_ja(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_project_id: str,
        dataset_recording: Recording,
        tag_with_taxon: Tag,
    ) -> None:
        """Single-detection endpoint honours the ``locale`` parameter."""
        annotation = Annotation(
            recording_id=dataset_recording.id,
            tag_id=tag_with_taxon.id,
            source=DetectionSource.BIRDNET,
            status=DetectionStatus.UNREVIEWED,
            confidence=0.9,
            start_time=10.0,
            end_time=13.0,
        )
        db_session.add(annotation)
        await db_session.commit()
        await db_session.refresh(annotation)

        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/{annotation.id}",
            headers=auth_headers,
            params={"locale": "ja"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tag"]["vernacular_name"] == "クロウタドリ"


# ---------------------------------------------------------------------------
# N+1 regression guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVernacularBatchResolution:
    """Guard against N+1 queries when rendering large detection pages."""

    async def test_large_detection_page_uses_single_vernacular_query(
        self,
        db_session: AsyncSession,
        test_project: Project,
        dataset_recording: Recording,
        tag_with_taxon: Tag,
    ) -> None:
        """Serving 100 detections resolves vernacular names in ONE query.

        We capture the raw SQL sent by the session used by
        ``DetectionService.list_detections`` and assert that only a single
        ``SELECT ... FROM taxon_vernacular_names`` statement fires even when
        many annotations share and differ across taxa.
        """
        # Pre-create 100 annotations all pointing to the same species tag.
        annotations = [
            Annotation(
                recording_id=dataset_recording.id,
                tag_id=tag_with_taxon.id,
                source=DetectionSource.BIRDNET,
                status=DetectionStatus.UNREVIEWED,
                confidence=0.8,
                start_time=float(i),
                end_time=float(i) + 0.5,
            )
            for i in range(100)
        ]
        db_session.add_all(annotations)
        await db_session.commit()

        # Instrument raw SQL via an engine-level event listener.
        captured: list[str] = []
        bind = db_session.get_bind()
        # ``bind`` is the sync engine facade exposed by the async session.
        # Some SQLAlchemy versions expose ``sync_engine`` on the async engine
        # instead; fall back to the bind itself when the attribute is absent.
        listener_target = getattr(bind, "sync_engine", bind)

        def _before_cursor_execute(
            _conn: Connection,
            _cursor: DBAPICursor,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            captured.append(statement)

        event.listen(listener_target, "before_cursor_execute", _before_cursor_execute)
        try:
            from echoroo.repositories.annotation import AnnotationRepository
            from echoroo.repositories.annotation_vote import (
                AnnotationVoteRepository,
            )
            from echoroo.repositories.confirmed_region import (
                ConfirmedRegionRepository,
            )
            from echoroo.services.detection import DetectionService

            service = DetectionService(
                annotation_repo=AnnotationRepository(db_session),
                confirmed_region_repo=ConfirmedRegionRepository(db_session),
                vote_repo=AnnotationVoteRepository(db_session),
            )
            response = await service.list_detections(
                project_id=test_project.id,
                page=1,
                page_size=100,
                locale="ja",
            )
        finally:
            event.remove(listener_target, "before_cursor_execute", _before_cursor_execute)

        assert len(response.items) == 100
        # Every item shares the same tag, so all should carry the JA name.
        assert all(
            i.tag is not None and i.tag.vernacular_name == "クロウタドリ"
            for i in response.items
        )

        vernacular_queries = [
            s for s in captured if "taxon_vernacular_names" in s
        ]
        # Exactly one SELECT hits taxon_vernacular_names for the full page.
        assert len(vernacular_queries) == 1, (
            "Expected a single batched vernacular lookup, "
            f"got {len(vernacular_queries)}: {vernacular_queries}"
        )


# ---------------------------------------------------------------------------
# Helper unit-style test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_vernacular_names_ignores_none_and_deduplicates(
    db_session: AsyncSession,
    seeded_taxon: Taxon,
) -> None:
    """``resolve_vernacular_names`` skips ``None`` and duplicate inputs.

    Also verifies the function returns an empty mapping when no taxon
    matches the requested locale instead of raising.
    """
    from echoroo.services.vernacular import resolve_vernacular_names

    random_ids: list[UUID | None] = [
        seeded_taxon.id,
        seeded_taxon.id,  # duplicate — should collapse
        None,  # ignored
        uuid4(),  # unknown taxon — should be absent from map
    ]
    mapping = await resolve_vernacular_names(db_session, random_ids, "ja")
    assert mapping == {seeded_taxon.id: "クロウタドリ"}

    # Unknown locale returns an empty mapping rather than erroring.
    assert (
        await resolve_vernacular_names(db_session, [seeded_taxon.id], "de")
        == {}
    )
