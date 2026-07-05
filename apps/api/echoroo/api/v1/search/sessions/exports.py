"""CSV export handlers for search sessions.

Two streaming export routes (recordings-similarity summary and the
detection-annotation export) plus their helper chain. These are unmounted
from ``/api/v1``; the ``/web-api/v1`` BFF delegates to them as helpers.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from echoroo.api.v1.search.deps import AuthorizedSearchSessionServiceDep
from echoroo.api.v1.search.sessions._shared import _get_query_vectors_from_session
from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser

logger = logging.getLogger(__name__)


async def _build_species_labels(
    session: Any,
    db: Any,
) -> tuple[dict[str, str], list[str]]:
    """Resolve the species_key list and their scientific-name labels.

    Responsibilities consolidated from the original inline block:

    - Pulls the ``results`` dict out of ``session.results`` and validates
      its shape, raising 404 on malformed or empty results using the
      documented detail strings.
    - Computes ``species_keys`` as the ordered list of result keys
      (tag UUIDs) in the session's results payload.
    - Builds ``species_labels`` (species_key → scientific_name) via a
      two-pass lookup whose ordering MUST be preserved for behaviour
      parity: first pass matches by ``species_config[*].tag_id``, second
      pass falls back to a ``tags`` table query by scientific_name for
      any keys still unmapped (typical when the session was created from
      a URL-source tag with no pre-existing tag_id).

    Args:
        session: SearchSession ORM instance. ``results`` is the canonical
            source for ``species_keys``; ``species_config`` (optional) is
            used for display labels.
        db: AsyncSession used for the tags fallback lookup.

    Returns:
        Tuple of (species_labels, species_keys). ``species_labels`` only
        contains entries for keys that were successfully resolved.

    Raises:
        HTTPException 404: When ``session.results["results"]`` is not a
            dict (``"Session has no results to export"``) or contains no
            species keys (``"Session has no species results to export"``).
    """
    # Extract all species from the session's results.
    # Each result key matches the species_config tag_id used during search.
    raw_results = session.results.get("results")
    if not isinstance(raw_results, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session has no results to export",
        )

    species_keys: list[str] = list(raw_results.keys())
    if not species_keys:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session has no species results to export",
        )

    # Build display name mapping: species_key -> scientific name.
    #
    # The keys in raw_results are tag UUIDs. species_config entries may have
    # tag_id=null (when the search was created from a URL source without an
    # existing tag), so we fall back to looking up the tag by scientific_name.
    species_labels: dict[str, str] = {}

    # First pass: map by tag_id when available
    if session.species_config and isinstance(session.species_config, list):
        for sp_cfg in session.species_config:
            if not isinstance(sp_cfg, dict):
                continue
            sp_tag_id = str(sp_cfg.get("tag_id") or "")
            sp_sci_name = str(sp_cfg.get("scientific_name") or "")
            label = sp_sci_name or sp_tag_id or "Unknown"
            for key in species_keys:
                if sp_tag_id and key == sp_tag_id:
                    species_labels[key] = label

    # Second pass: for keys still unmapped, look up tag by scientific_name
    unmapped_keys = [k for k in species_keys if k not in species_labels]
    if unmapped_keys and session.species_config and isinstance(session.species_config, list):
        sci_names_in_config = [
            str(sp_cfg.get("scientific_name") or "")
            for sp_cfg in session.species_config
            if isinstance(sp_cfg, dict) and sp_cfg.get("scientific_name")
        ]
        if sci_names_in_config:
            tag_lookup_sql = text(
                "SELECT id::text, scientific_name FROM tags "
                "WHERE id = ANY(:ids) OR scientific_name = ANY(:names)"
            )
            tag_rows = (
                await db.execute(
                    tag_lookup_sql,
                    {"ids": unmapped_keys, "names": sci_names_in_config},
                )
            ).fetchall()
            # Build: tag_id -> scientific_name from DB
            tag_id_to_sci: dict[str, str] = {str(row[0]): str(row[1]) for row in tag_rows if row[1]}
            for key in unmapped_keys:
                if key in tag_id_to_sci:
                    species_labels[key] = tag_id_to_sci[key]

    return species_labels, species_keys


async def _fetch_session_recordings(
    session: Any,
    project_id: UUID,
    db: Any,
) -> list[tuple[str, str, str | None]]:
    """Fetch the project's recordings (optionally filtered by dataset_id).

    Extracts the ``dataset_id`` filter from ``session.parameters`` (nullable)
    and returns every recording in the project whose dataset matches.
    Timestamps are converted into the dataset's configured timezone (falling
    back to UTC) so the CSV consumer sees wall-clock times consistent with
    the session-detail UI.

    Args:
        session: SearchSession ORM instance (``parameters`` attr read).
        project_id: Project UUID used to scope the recordings query.
        db: AsyncSession.

    Returns:
        Ordered list of ``(recording_id, recording_filename, recording_datetime)``
        tuples sorted by recording_datetime ASC (NULLs last, then filename
        ASC for stable ordering).
    """
    # Determine optional dataset filter from session parameters
    dataset_id_str: str | None = None
    if session.parameters and session.parameters.get("dataset_id"):
        dataset_id_str = str(session.parameters["dataset_id"])

    # Returns: recording_id, recording_filename, recording_datetime (in dataset tz)
    dataset_filter_sql = "AND d.id = :dataset_id" if dataset_id_str else ""
    recordings_sql = text(
        f"""
        SELECT
            r.id::text AS recording_id,
            r.filename AS recording_filename,
            CASE
                WHEN r.datetime IS NOT NULL THEN
                    (r.datetime AT TIME ZONE COALESCE(d.datetime_timezone, 'UTC'))::text
                ELSE NULL
            END AS recording_datetime
        FROM recordings r
        JOIN datasets d ON r.dataset_id = d.id
        WHERE d.project_id = :project_id
          {dataset_filter_sql}
        ORDER BY r.datetime ASC NULLS LAST, r.filename ASC
        """
    )
    rec_params: dict[str, object] = {"project_id": str(project_id)}
    if dataset_id_str:
        rec_params["dataset_id"] = dataset_id_str

    rec_rows = (await db.execute(recordings_sql, rec_params)).fetchall()

    # Build an ordered list of (recording_id, filename, datetime_str)
    return [
        (str(row.recording_id), str(row.recording_filename), row.recording_datetime)
        for row in rec_rows
    ]


async def _resolve_locale_common_names(
    session: Any,
    species_keys: list[str],
    species_labels: dict[str, str],
    locale: str,
    db: Any,
) -> dict[str, str]:
    """Resolve ``species_key -> common_name`` for the export-recordings CSV.

    Mirrors the locale-enrichment guard used by the list/detail routes: when
    ``_enrich_species_config_with_locale`` raises (e.g. transient GBIF outage
    or an internal SQLAlchemy greenlet error), we MUST NOT bubble the failure
    up as a 500. Instead we log a warning and fall back to the raw
    ``session.species_config``.  If the raw config still has ``common_name``
    values populated (typical when the search was created from a local tag),
    those are preserved in the returned mapping so the CSV does not suddenly
    lose its ``common_name`` column content.

    Args:
        session: SearchSession ORM instance (``species_config`` attr read).
        species_keys: Ordered list of species keys (tag UUIDs) from the
            session results. Only keys present here are populated in the
            returned dict.
        species_labels: Mapping of species_key → scientific_name used to
            join against the ``sci_name -> common_name`` lookup.
        locale: Locale string (``en``/``ja``) passed through to the
            enrichment helper.
        db: AsyncSession for GBIF / vernacular lookups.

    Returns:
        Dict keyed by species_key with common_name values. Empty when
        ``species_config`` is missing/invalid, or when neither the enriched
        nor the raw config yielded a matching ``common_name`` for any of
        the given ``species_keys``.
    """
    species_common_names: dict[str, str] = {}
    if not (session.species_config and isinstance(session.species_config, list)):
        return species_common_names

    from echoroo.api.v1.search.utils import _enrich_species_config_with_locale

    try:
        enriched_config = await _enrich_species_config_with_locale(
            list(session.species_config), locale, db
        )
    except Exception:
        logger.warning(
            "Failed to enrich species_config for export-recordings (locale=%r); "
            "falling back to raw species_config",
            locale,
            exc_info=True,
        )
        enriched_config = list(session.species_config)

    # Build sci_name -> common_name from enriched (or raw-fallback) config
    sci_to_common: dict[str, str] = {}
    for sp_cfg in enriched_config:
        if not isinstance(sp_cfg, dict):
            continue
        sp_sci = str(sp_cfg.get("scientific_name") or "")
        sp_common = str(sp_cfg.get("common_name") or "")
        if sp_sci and sp_common:
            sci_to_common[sp_sci] = sp_common

    # Map species_key -> common_name using species_labels (key -> sci_name)
    for key in species_keys:
        sci_name = species_labels.get(key, "")
        if sci_name in sci_to_common:
            species_common_names[key] = sci_to_common[sci_name]

    return species_common_names


async def _compute_similarity_aggregates(
    session: Any,
    species_keys: list[str],
    all_recordings: list[tuple[str, str, str | None]],
    db: Any,
) -> dict[str, dict[str, dict[str, float]]]:
    """Compute per-(species, recording) similarity aggregates.

    For each species key in the session's results, runs the stored query
    vectors against every project embedding via ``<=>`` cosine distance and
    rolls the similarities up to one MAX/MIN/AVG row per recording_id.
    Species with no stored query vectors (e.g. results were truncated or
    the originating embeddings have been deleted) are silently skipped —
    the CSV writer will fall back to empty similarity cells for them.

    The ``all_recordings`` argument is accepted to satisfy the original
    "aggregate only over recordings we're going to emit" contract, even
    though the current SQL still computes over all project embeddings.
    Passing the list keeps the route-level data flow explicit and lets a
    future optimisation restrict the set of recordings without changing
    the helper's signature.

    Args:
        session: SearchSession ORM instance (``model_name``, ``parameters``
            attrs read; the dataset filter is derived here).
        species_keys: Ordered list of species keys to aggregate over.
        all_recordings: The recordings list returned by
            ``_fetch_session_recordings``. Not directly used by the SQL
            today but kept in the signature per plan (Codex M-2).
        db: AsyncSession.

    Returns:
        Nested dict ``{species_key: {recording_id: {max_sim, min_sim, avg_sim}}}``.
        Missing species and missing recordings default to an empty inner
        dict so callers can use ``.get(...)`` chaining.
    """
    del (
        all_recordings
    )  # accepted for plan-prescribed signature parity; SQL spans all project embeddings

    # Determine optional dataset filter from session parameters.
    dataset_id_str: str | None = None
    if session.parameters and session.parameters.get("dataset_id"):
        dataset_id_str = str(session.parameters["dataset_id"])

    model_name = session.model_name or "perch"
    dataset_filter = "AND d.id = :dataset_id" if dataset_id_str else ""
    project_id_str = str(session.project_id)

    agg: dict[str, dict[str, dict[str, float]]] = {}

    for sp_key in species_keys:
        query_vectors = await _get_query_vectors_from_session(session, db, species_key=sp_key)
        if not query_vectors:
            continue

        # Build UNION ALL for multi-vector MAX similarity per embedding
        union_parts: list[str] = []
        sim_params: dict[str, object] = {
            "project_id": project_id_str,
            "model_name": model_name,
        }
        if dataset_id_str:
            sim_params["dataset_id"] = dataset_id_str

        for idx, qv in enumerate(query_vectors):
            vec_literal = "[" + ",".join(str(v) for v in qv) + "]"
            param_key = f"qv_{idx}"
            sim_params[param_key] = vec_literal
            union_parts.append(
                f"""
                SELECT
                    e.id AS embedding_id,
                    e.recording_id,
                    1 - (e.vector <=> CAST(:{param_key} AS vector)) AS similarity
                FROM embeddings e
                JOIN recordings r ON e.recording_id = r.id
                JOIN datasets d   ON r.dataset_id   = d.id
                WHERE d.project_id = :project_id
                  AND e.model_name  = :model_name
                  {dataset_filter}
                """
            )

        union_sql = " UNION ALL ".join(union_parts)
        agg_sql = text(
            f"""
            WITH all_sims AS (
                {union_sql}
            ),
            best_per_embedding AS (
                SELECT recording_id, MAX(similarity) AS similarity
                FROM all_sims
                GROUP BY recording_id, embedding_id
            )
            SELECT
                recording_id::text,
                MAX(similarity) AS max_sim,
                MIN(similarity) AS min_sim,
                AVG(similarity) AS avg_sim
            FROM best_per_embedding
            GROUP BY recording_id
            """
        )
        rows = (await db.execute(agg_sql, sim_params)).fetchall()
        species_agg = agg.setdefault(sp_key, {})
        for row in rows:
            species_agg[str(row[0])] = {
                "max_sim": float(row[1]),
                "min_sim": float(row[2]),
                "avg_sim": float(row[3]),
            }

    return agg


_EXPORT_CSV_HEADER: list[str] = [
    "recording_filename",
    "recording_datetime",
    "scientific_name",
    "common_name",
    "max_similarity",
    "min_similarity",
    "avg_similarity",
]


def _write_recordings_csv(
    session: Any,
    all_recordings: list[tuple[str, str, str | None]],
    species_labels: dict[str, str],
    species_common_names: dict[str, str],
    species_keys: list[str],
    agg: dict[str, dict[str, dict[str, float]]],
) -> tuple[str, str]:
    """Serialise the export-recordings CSV body and compute its filename.

    Unifies the empty-state path (no recordings → header-only CSV) and
    the populated path (one row per ``(recording, species)`` with
    aggregated similarities). Both paths share the same writer, header
    row, and ``search_summary_{safe_name}_{YYYYMMDD}.csv`` filename
    template — a user whose project happens to be empty must still see a
    correctly-named download.

    The returned body is a ``str``, not ``bytes``: the route streams it
    via ``StreamingResponse(iter([csv_content]))`` exactly as the original
    inline code did.  The ``safe_name`` sanitisation used for the filename
    is byte-for-byte identical to the original (same six replacements in
    the same order).

    Args:
        session: SearchSession ORM instance. ``session.name`` and
            ``session.id`` are used for the filename.
        all_recordings: Output of ``_fetch_session_recordings`` — iteration
            order is preserved as the row order in the CSV.
        species_labels: species_key → scientific_name.
        species_common_names: species_key → common_name (possibly empty).
        species_keys: Ordered list of species keys to emit per recording.
        agg: Output of ``_compute_similarity_aggregates``; ``{}`` when no
            recordings were found.

    Returns:
        Tuple of (csv_content, filename).
    """
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_EXPORT_CSV_HEADER)

    for rec_id, rec_filename, rec_datetime in all_recordings:
        for sp_key in species_keys:
            sci_name = species_labels.get(sp_key, sp_key)
            common_name = species_common_names.get(sp_key, "")
            rec_agg = agg.get(sp_key, {}).get(rec_id)
            if rec_agg is not None:
                writer.writerow(
                    [
                        rec_filename,
                        rec_datetime or "",
                        sci_name,
                        common_name,
                        f"{rec_agg['max_sim']:.4f}",
                        f"{rec_agg['min_sim']:.4f}",
                        f"{rec_agg['avg_sim']:.4f}",
                    ]
                )
            else:
                writer.writerow(
                    [
                        rec_filename,
                        rec_datetime or "",
                        sci_name,
                        common_name,
                        "",
                        "",
                        "",
                    ]
                )

    csv_content = output.getvalue()
    date_str = datetime.now(UTC).strftime("%Y%m%d")
    safe_name = (
        (session.name or str(session.id))
        .replace('"', "_")
        .replace("\n", "_")
        .replace("\r", "_")
        .replace(" ", "_")
        .replace("/", "-")
    )
    filename = f"search_summary_{safe_name}_{date_str}.csv"
    return csv_content, filename


async def export_search_session_recordings_csv(
    project_id: UUID,
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
    locale: str = Query(default="en", description="Locale for common names (en, ja)"),
) -> StreamingResponse:
    """Export per-(recording × species) aggregated similarity results as CSV.

    For each species in the session, computes similarity for all project
    recordings using the stored query vectors. All recordings are included
    (those without embeddings get NULL similarities). Produces one row per
    (recording, species) combination sorted by recording_datetime ASC.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        request: FastAPI request
        current_user: Authenticated caller
        db: Database session
        session_service: Authorized search session service

    Returns:
        CSV file as streaming response with columns:
        recording_filename, recording_datetime, species,
        max_similarity, min_similarity, avg_similarity

    Raises:
        403: Access denied to project
        404: Session not found or has no results
    """
    from echoroo.core.actions import SEARCH_SESSION_EXPORT_RECORDINGS_ACTION
    from echoroo.core.permissions import gate_action

    await gate_action(
        action=SEARCH_SESSION_EXPORT_RECORDINGS_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found"
        )

    if not session.results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session has no results to export",
        )

    # Snapshot every ORM attribute we will need into a plain-old-data proxy
    # BEFORE any helper that may flush/commit/rollback the DB session.  The
    # locale-enrichment chain (``_resolve_locale_common_names`` ->
    # ``_enrich_species_config_with_locale`` -> ``_resolve_vernacular_via_gbif``)
    # transparently caches new GBIF Taxon / TaxonVernacularName rows and runs
    # ``await db.rollback()`` inside its duplicate-race guard.  SQLAlchemy's
    # ``rollback()`` EXPIRES every ORM-tracked attribute on every instance in
    # the session, regardless of ``expire_on_commit``.  Any subsequent access
    # to ``session.parameters`` / ``session.name`` / ``session.results`` would
    # then trigger an implicit lazy-load outside the async context and raise
    # ``MissingGreenlet``.  The POD proxy is immune because its values are
    # concrete dict/str/UUID copies held in memory.
    from types import SimpleNamespace

    session_snapshot = SimpleNamespace(
        id=session.id,
        name=session.name,
        project_id=session.project_id,
        model_name=session.model_name,
        parameters=dict(session.parameters) if session.parameters else None,
        results=dict(session.results) if session.results else None,
        species_config=list(session.species_config) if session.species_config else None,
    )

    # Extract species_labels + species_keys (tag_id lookup + sci_name fallback).
    # The helper owns the two 404 paths for malformed / empty results.
    species_labels, species_keys = await _build_species_labels(session_snapshot, db)

    # Build common name mapping using the same enrichment as session detail API.
    # Locale enrichment is best-effort: a transient GBIF outage or an internal
    # SQLAlchemy error must NOT cause the export to fail. Mirror the guard used
    # by the list/detail routes — degrade to scientific names when enrichment
    # raises.
    species_common_names = await _resolve_locale_common_names(
        session_snapshot, species_keys, species_labels, locale, db
    )

    # Fetch all recordings for this project (with the optional dataset filter
    # from session.parameters applied inside the helper).
    all_recordings = await _fetch_session_recordings(session_snapshot, project_id, db)

    # For each species, compute similarity against ALL embeddings via SQL
    # (same pattern as distribution/time-distribution APIs).
    # Aggregate per recording: MAX, MIN, AVG similarity.
    agg = (
        await _compute_similarity_aggregates(session_snapshot, species_keys, all_recordings, db)
        if all_recordings
        else {}
    )

    csv_content, filename = _write_recordings_csv(
        session_snapshot,
        all_recordings,
        species_labels,
        species_common_names,
        species_keys,
        agg,
    )
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def export_search_session_csv(
    project_id: UUID,
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
) -> StreamingResponse:
    """Export search session annotations as CSV.

    Phase 17 backlog A-5 (Hybrid Contract): the underlying export
    pipeline now streams row-by-row and re-checks the EXPORT permission
    every ``CSV_RECHECK_INTERVAL`` rows. Pre-start gating is performed
    via :func:`gate_action` (was implicitly via
    ``AuthorizedSearchSessionServiceDep`` → ``check_project_access``;
    we keep that for the session lookup and add the explicit Action
    gate so the mid-stream guard has a canonical Action to re-evaluate).

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        request: FastAPI request (used by the streaming guard).
        current_user: Authenticated caller (used by the streaming guard).
        db: Database session
        session_service: Authorized search session service

    Returns:
        CSV file as streaming response

    Raises:
        403: Access denied to project
        404: Session not found
    """
    # Local import — DETECTION_EXPORT_CSV_ACTION lives in echoroo.core.actions
    # which depends on routers; lazy to avoid a top-level cycle.
    from echoroo.core.actions import DETECTION_EXPORT_CSV_ACTION
    from echoroo.core.permissions import gate_action
    from echoroo.services.detection_export import DetectionExportService

    await gate_action(
        action=DETECTION_EXPORT_CSV_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found"
        )

    export_service = DetectionExportService(db)
    body_iterator = export_service.export_csv_stream(
        project_id=project_id,
        action=DETECTION_EXPORT_CSV_ACTION,
        current_user=current_user,
        request=request,
        stream_type="csv_export_search_session",
        search_session_id=session_id,
    )

    date_str = datetime.now(UTC).strftime("%Y%m%d")
    safe_name = (
        (session.name or str(session_id))
        .replace('"', "_")
        .replace("\n", "_")
        .replace("\r", "_")
        .replace(" ", "_")
        .replace("/", "-")
    )
    filename = f"search_session_{safe_name}_{date_str}.csv"
    return StreamingResponse(
        body_iterator,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
