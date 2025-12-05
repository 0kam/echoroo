"""API functions to interact with embeddings."""

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import models, schemas
from echoroo.api.common import BaseAPI, create_object

__all__ = [
    "ClipEmbeddingAPI",
    "SoundEventEmbeddingAPI",
    "clip_embeddings",
    "get_clip_embedding_count",
    "get_random_clips_with_embeddings",
    "search_similar_clips",
    "search_similar_clips_advanced",
    "sound_event_embeddings",
]


class ClipEmbeddingAPI(
    BaseAPI[
        UUID,
        models.ClipEmbedding,
        schemas.ClipEmbedding,
        schemas.ClipEmbedding,  # No separate create schema
        schemas.ClipEmbedding,  # No separate update schema
    ]
):
    """API for managing clip embeddings."""

    _model = models.ClipEmbedding
    _schema = schemas.ClipEmbedding

    async def create(
        self,
        session: AsyncSession,
        clip: schemas.Clip,
        model_run: schemas.ModelRun,
        embedding: list[float],
        **kwargs,
    ) -> schemas.ClipEmbedding:
        """Create embedding for a clip.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        clip
            Clip to create embedding for.
        model_run
            Model run that generated the embedding.
        embedding
            Embedding vector (list of floats).
        **kwargs
            Additional keyword arguments.

        Returns
        -------
        schemas.ClipEmbedding
            Created clip embedding.
        """
        obj = await create_object(
            session,
            models.ClipEmbedding,
            clip_id=clip.id,
            model_run_id=model_run.id,
            embedding=embedding,
            **kwargs,
        )
        await session.refresh(obj, ["clip", "model_run"])
        return schemas.ClipEmbedding.model_validate(obj)

    async def find_similar(
        self,
        session: AsyncSession,
        embedding: list[float],
        model_run_id: int,
        limit: int = 20,
        min_similarity: float = 0.7,
    ) -> list[tuple[schemas.ClipEmbedding, float]]:
        """Find similar clips using cosine similarity.

        Uses pgvector's <=> operator for cosine distance.
        similarity = 1 - cosine_distance

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        embedding
            Query embedding vector.
        model_run_id
            Model run ID to filter by.
        limit
            Maximum number of results.
        min_similarity
            Minimum similarity threshold (0.0 to 1.0).

        Returns
        -------
        list[tuple[schemas.ClipEmbedding, float]]
            List of (embedding, similarity) tuples.
        """
        # Convert embedding to string format for pgvector
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

        # Query using pgvector cosine distance
        stmt = text("""
            SELECT 
                ce.*,
                1 - (ce.embedding <=> :query_embedding::vector) as similarity
            FROM clip_embedding ce
            WHERE ce.model_run_id = :model_run_id
            AND 1 - (ce.embedding <=> :query_embedding::vector) >= :min_similarity
            ORDER BY ce.embedding <=> :query_embedding::vector
            LIMIT :limit
        """)

        result = await session.execute(
            stmt,
            {
                "query_embedding": embedding_str,
                "model_run_id": model_run_id,
                "min_similarity": min_similarity,
                "limit": limit,
            },
        )

        rows = result.fetchall()
        results = []

        for row in rows:
            # Fetch the full object with relationships
            obj = await session.get(
                models.ClipEmbedding, row.id, options=[]
            )
            if obj:
                await session.refresh(obj, ["clip", "model_run"])
                emb = schemas.ClipEmbedding.model_validate(obj)
                results.append((emb, row.similarity))

        return results

    async def get_by_clip_and_model_run(
        self,
        session: AsyncSession,
        clip_uuid: UUID,
        model_run_uuid: UUID | None = None,
    ) -> schemas.ClipEmbedding | None:
        """Get embedding for a clip, optionally filtered by model run.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        clip_uuid
            UUID of the clip.
        model_run_uuid
            Optional UUID of the model run to filter by.

        Returns
        -------
        schemas.ClipEmbedding | None
            The clip embedding or None if not found.
        """
        stmt = (
            select(models.ClipEmbedding)
            .join(models.Clip, models.ClipEmbedding.clip_id == models.Clip.id)
            .where(models.Clip.uuid == clip_uuid)
        )

        if model_run_uuid is not None:
            stmt = stmt.join(
                models.ModelRun,
                models.ClipEmbedding.model_run_id == models.ModelRun.id,
            ).where(models.ModelRun.uuid == model_run_uuid)

        result = await session.execute(stmt)
        obj = result.scalar_one_or_none()

        if obj is None:
            return None

        await session.refresh(obj, ["clip", "model_run"])
        return schemas.ClipEmbedding.model_validate(obj)


class SoundEventEmbeddingAPI(
    BaseAPI[
        UUID,
        models.SoundEventEmbedding,
        schemas.SoundEventEmbedding,
        schemas.SoundEventEmbedding,
        schemas.SoundEventEmbedding,
    ]
):
    """API for managing sound event embeddings."""

    _model = models.SoundEventEmbedding
    _schema = schemas.SoundEventEmbedding

    async def create(
        self,
        session: AsyncSession,
        sound_event: schemas.SoundEvent,
        model_run: schemas.ModelRun,
        embedding: list[float],
        **kwargs,
    ) -> schemas.SoundEventEmbedding:
        """Create embedding for a sound event."""
        obj = await create_object(
            session,
            models.SoundEventEmbedding,
            sound_event_id=sound_event.id,
            model_run_id=model_run.id,
            embedding=embedding,
            **kwargs,
        )
        await session.refresh(obj, ["sound_event", "model_run"])
        return schemas.SoundEventEmbedding.model_validate(obj)

    async def find_similar(
        self,
        session: AsyncSession,
        embedding: list[float],
        model_run_id: int,
        limit: int = 20,
        min_similarity: float = 0.7,
    ) -> list[tuple[schemas.SoundEventEmbedding, float]]:
        """Find similar sound events using cosine similarity."""
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

        stmt = text("""
            SELECT 
                se.*,
                1 - (se.embedding <=> :query_embedding::vector) as similarity
            FROM sound_event_embedding se
            WHERE se.model_run_id = :model_run_id
            AND 1 - (se.embedding <=> :query_embedding::vector) >= :min_similarity
            ORDER BY se.embedding <=> :query_embedding::vector
            LIMIT :limit
        """)

        result = await session.execute(
            stmt,
            {
                "query_embedding": embedding_str,
                "model_run_id": model_run_id,
                "min_similarity": min_similarity,
                "limit": limit,
            },
        )

        rows = result.fetchall()
        results = []

        for row in rows:
            obj = await session.get(
                models.SoundEventEmbedding, row.id, options=[]
            )
            if obj:
                await session.refresh(obj, ["sound_event", "model_run"])
                emb = schemas.SoundEventEmbedding.model_validate(obj)
                results.append((emb, row.similarity))

        return results

    async def get_by_sound_event_and_model_run(
        self,
        session: AsyncSession,
        sound_event_uuid: UUID,
        model_run_uuid: UUID | None = None,
    ) -> schemas.SoundEventEmbedding | None:
        """Get embedding for a sound event, optionally filtered by model run.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        sound_event_uuid
            UUID of the sound event.
        model_run_uuid
            Optional UUID of the model run to filter by.

        Returns
        -------
        schemas.SoundEventEmbedding | None
            The sound event embedding or None if not found.
        """
        stmt = (
            select(models.SoundEventEmbedding)
            .join(
                models.SoundEvent,
                models.SoundEventEmbedding.sound_event_id == models.SoundEvent.id,
            )
            .where(models.SoundEvent.uuid == sound_event_uuid)
        )

        if model_run_uuid is not None:
            stmt = stmt.join(
                models.ModelRun,
                models.SoundEventEmbedding.model_run_id == models.ModelRun.id,
            ).where(models.ModelRun.uuid == model_run_uuid)

        result = await session.execute(stmt)
        obj = result.scalar_one_or_none()

        if obj is None:
            return None

        await session.refresh(obj, ["sound_event", "model_run"])
        return schemas.SoundEventEmbedding.model_validate(obj)


clip_embeddings = ClipEmbeddingAPI()
sound_event_embeddings = SoundEventEmbeddingAPI()


async def get_clip_embedding_count(
    session: AsyncSession,
    model_name: str,
    dataset_uuids: list[UUID] | None = None,
) -> int:
    """Get the total count of clip embeddings for a model name.

    Parameters
    ----------
    session
        SQLAlchemy AsyncSession.
    model_name
        Name of the model to count embeddings for.
    dataset_uuids
        Optional list of dataset UUIDs to filter by.

    Returns
    -------
    int
        Total count of embeddings.
    """
    query = """
        SELECT COUNT(*)
        FROM clip_embedding ce
        JOIN model_run mr ON ce.model_run_id = mr.id
        JOIN clip c ON ce.clip_id = c.id
        JOIN recording r ON c.recording_id = r.id
        WHERE mr.name = :model_name
    """

    params: dict = {"model_name": model_name}

    if dataset_uuids:
        query += " AND r.dataset_id IN (SELECT id FROM dataset WHERE uuid IN :dataset_uuids)"
        params["dataset_uuids"] = tuple(str(u) for u in dataset_uuids)

    stmt = text(query)
    result = await session.execute(stmt, params)
    return result.scalar() or 0


async def search_similar_clips(
    session: AsyncSession,
    embedding: list[float],
    model_name: str,
    limit: int = 20,
    min_similarity: float = 0.7,
) -> list[schemas.EmbeddingSearchResult]:
    """Search for similar clips across all model runs with the given model name.

    Parameters
    ----------
    session
        SQLAlchemy AsyncSession.
    embedding
        Query embedding vector.
    model_name
        Name of the model to search embeddings for.
    limit
        Maximum number of results.
    min_similarity
        Minimum similarity threshold (0.0 to 1.0).

    Returns
    -------
    list[schemas.EmbeddingSearchResult]
        List of search results sorted by similarity.
    """
    # Convert embedding to string format for pgvector
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

    # Query using pgvector cosine distance, filtering by model name
    stmt = text("""
        SELECT
            ce.id,
            ce.clip_id,
            ce.model_run_id,
            1 - (ce.embedding <=> :query_embedding::vector) as similarity
        FROM clip_embedding ce
        JOIN model_run mr ON ce.model_run_id = mr.id
        WHERE mr.name = :model_name
        AND 1 - (ce.embedding <=> :query_embedding::vector) >= :min_similarity
        ORDER BY ce.embedding <=> :query_embedding::vector
        LIMIT :limit
    """)

    result = await session.execute(
        stmt,
        {
            "query_embedding": embedding_str,
            "model_name": model_name,
            "min_similarity": min_similarity,
            "limit": limit,
        },
    )

    rows = result.fetchall()
    results = []

    for row in rows:
        # Fetch the clip and model_run
        clip_obj = await session.get(models.Clip, row.clip_id)
        model_run_obj = await session.get(models.ModelRun, row.model_run_id)

        if clip_obj is not None and model_run_obj is not None:
            clip = schemas.Clip.model_validate(clip_obj)
            model_run = schemas.ModelRun.model_validate(model_run_obj)

            results.append(
                schemas.EmbeddingSearchResult(
                    clip=clip,
                    sound_event=None,
                    similarity=row.similarity,
                    model_run=model_run,
                )
            )

    return results


async def search_similar_clips_advanced(
    session: AsyncSession,
    embedding: list[float],
    model_name: str,
    dataset_uuids: list[UUID] | None = None,
    recording_uuids: list[UUID] | None = None,
    limit: int = 20,
    min_similarity: float = 0.7,
) -> tuple[list[schemas.SearchResultItem], int]:
    """Search for similar clips with advanced filtering options.

    Parameters
    ----------
    session
        SQLAlchemy AsyncSession.
    embedding
        Query embedding vector.
    model_name
        Name of the model to search embeddings for.
    dataset_uuids
        Optional list of dataset UUIDs to filter results.
    recording_uuids
        Optional list of recording UUIDs to filter results.
    limit
        Maximum number of results.
    min_similarity
        Minimum similarity threshold (0.0 to 1.0).

    Returns
    -------
    tuple[list[schemas.SearchResultItem], int]
        List of search results and the total count of embeddings searched.
    """
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

    # Build dynamic query with optional filters
    base_query = """
        SELECT
            ce.id,
            ce.clip_id,
            ce.model_run_id,
            c.recording_id,
            1 - (ce.embedding <=> :query_embedding::vector) as similarity
        FROM clip_embedding ce
        JOIN model_run mr ON ce.model_run_id = mr.id
        JOIN clip c ON ce.clip_id = c.id
        JOIN recording r ON c.recording_id = r.id
        WHERE mr.name = :model_name
        AND 1 - (ce.embedding <=> :query_embedding::vector) >= :min_similarity
    """

    params: dict = {
        "query_embedding": embedding_str,
        "model_name": model_name,
        "min_similarity": min_similarity,
        "limit": limit,
    }

    if dataset_uuids:
        base_query += " AND r.dataset_id IN (SELECT id FROM dataset WHERE uuid = ANY(:dataset_uuids))"
        params["dataset_uuids"] = [str(u) for u in dataset_uuids]

    if recording_uuids:
        base_query += " AND r.uuid = ANY(:recording_uuids)"
        params["recording_uuids"] = [str(u) for u in recording_uuids]

    base_query += """
        ORDER BY ce.embedding <=> :query_embedding::vector
        LIMIT :limit
    """

    # Get total count of embeddings being searched
    count_query = """
        SELECT COUNT(*)
        FROM clip_embedding ce
        JOIN model_run mr ON ce.model_run_id = mr.id
        JOIN clip c ON ce.clip_id = c.id
        JOIN recording r ON c.recording_id = r.id
        WHERE mr.name = :model_name
    """
    count_params: dict = {"model_name": model_name}

    if dataset_uuids:
        count_query += " AND r.dataset_id IN (SELECT id FROM dataset WHERE uuid = ANY(:dataset_uuids))"
        count_params["dataset_uuids"] = [str(u) for u in dataset_uuids]

    if recording_uuids:
        count_query += " AND r.uuid = ANY(:recording_uuids)"
        count_params["recording_uuids"] = [str(u) for u in recording_uuids]

    count_result = await session.execute(text(count_query), count_params)
    total_count = count_result.scalar() or 0

    # Execute main search query
    result = await session.execute(text(base_query), params)
    rows = result.fetchall()
    results = []

    for row in rows:
        # Fetch the clip with recording
        clip_obj = await session.get(models.Clip, row.clip_id)
        recording_obj = await session.get(models.Recording, row.recording_id)
        model_run_obj = await session.get(models.ModelRun, row.model_run_id)

        if clip_obj is not None and recording_obj is not None and model_run_obj is not None:
            # Refresh to load relationships
            await session.refresh(clip_obj, ["recording"])
            clip = schemas.Clip.model_validate(clip_obj)
            recording = schemas.Recording.model_validate(recording_obj)
            model_run = schemas.ModelRun.model_validate(model_run_obj)

            results.append(
                schemas.SearchResultItem(
                    clip=clip,
                    recording=recording,
                    similarity=row.similarity,
                    model_run=model_run,
                )
            )

    return results, total_count


async def get_random_clips_with_embeddings(
    session: AsyncSession,
    model_name: str,
    dataset_uuids: list[UUID] | None = None,
    limit: int = 10,
) -> tuple[list[schemas.SearchResultItem], int]:
    """Get random clips that have embeddings for exploration.

    Parameters
    ----------
    session
        SQLAlchemy AsyncSession.
    model_name
        Name of the model to get embeddings for.
    dataset_uuids
        Optional list of dataset UUIDs to filter results.
    limit
        Number of random clips to return.

    Returns
    -------
    tuple[list[schemas.SearchResultItem], int]
        List of random clips and the total count of available clips.
    """
    # Build dynamic query with optional filters
    base_query = """
        SELECT
            ce.id,
            ce.clip_id,
            ce.model_run_id,
            c.recording_id
        FROM clip_embedding ce
        JOIN model_run mr ON ce.model_run_id = mr.id
        JOIN clip c ON ce.clip_id = c.id
        JOIN recording r ON c.recording_id = r.id
        WHERE mr.name = :model_name
    """

    params: dict = {
        "model_name": model_name,
        "limit": limit,
    }

    if dataset_uuids:
        base_query += " AND r.dataset_id IN (SELECT id FROM dataset WHERE uuid = ANY(:dataset_uuids))"
        params["dataset_uuids"] = [str(u) for u in dataset_uuids]

    base_query += """
        ORDER BY RANDOM()
        LIMIT :limit
    """

    # Get total count
    count_query = """
        SELECT COUNT(*)
        FROM clip_embedding ce
        JOIN model_run mr ON ce.model_run_id = mr.id
        JOIN clip c ON ce.clip_id = c.id
        JOIN recording r ON c.recording_id = r.id
        WHERE mr.name = :model_name
    """
    count_params: dict = {"model_name": model_name}

    if dataset_uuids:
        count_query += " AND r.dataset_id IN (SELECT id FROM dataset WHERE uuid = ANY(:dataset_uuids))"
        count_params["dataset_uuids"] = [str(u) for u in dataset_uuids]

    count_result = await session.execute(text(count_query), count_params)
    total_count = count_result.scalar() or 0

    # Execute main query
    result = await session.execute(text(base_query), params)
    rows = result.fetchall()
    results = []

    for row in rows:
        clip_obj = await session.get(models.Clip, row.clip_id)
        recording_obj = await session.get(models.Recording, row.recording_id)
        model_run_obj = await session.get(models.ModelRun, row.model_run_id)

        if clip_obj is not None and recording_obj is not None and model_run_obj is not None:
            await session.refresh(clip_obj, ["recording"])
            clip = schemas.Clip.model_validate(clip_obj)
            recording = schemas.Recording.model_validate(recording_obj)
            model_run = schemas.ModelRun.model_validate(model_run_obj)

            results.append(
                schemas.SearchResultItem(
                    clip=clip,
                    recording=recording,
                    similarity=1.0,  # No similarity for random selection
                    model_run=model_run,
                )
            )

    return results, total_count
