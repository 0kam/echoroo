"""API functions for interacting with datasets."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import datetime
from collections import defaultdict
import io
import os
import tempfile
import uuid
import warnings
from pathlib import Path
from typing import BinaryIO, Generator, Sequence

import h3
import pandas as pd
import sqlalchemy as sa
from soundevent import data
from soundevent.io.aoef import AOEFObject, to_aeof
from sqlalchemy import select, tuple_
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnExpressionArgument
from sqlalchemy.ext.asyncio import AsyncSession
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from echoroo import exceptions, models, schemas
from echoroo.api import common
from echoroo.api.common import BaseAPI, UserResolutionMixin
from echoroo.api.common.permissions import (
    can_delete_dataset,
    can_edit_dataset,
    can_manage_project_datasets,
    can_view_dataset,
    filter_datasets_by_access,
)
from echoroo.api.io import aoef
from echoroo.api.users import ensure_system_user
from echoroo.api.recordings import recordings
from echoroo.core import files
from echoroo.filters.base import Filter
from echoroo.filters.recordings import DatasetFilter
from echoroo.system import get_settings

__all__ = [
    "DatasetAPI",
    "datasets",
]


class DatasetAPI(
    BaseAPI[
        uuid.UUID,
        models.Dataset,
        schemas.Dataset,
        schemas.DatasetCreate,
        schemas.DatasetUpdate,
    ],
    UserResolutionMixin,
):
    _model = models.Dataset
    _schema = schemas.Dataset

    async def _ensure_project_manager(
        self,
        session: AsyncSession,
        project_id: str,
        user: models.User,
    ) -> None:
        allowed = await can_manage_project_datasets(session, project_id, user)
        if not allowed:
            raise exceptions.PermissionDeniedError(
                "You must be a project manager to perform this action"
            )

    async def _eager_load_relationships(
        self,
        session: AsyncSession,
        db_obj: models.Dataset,
    ) -> models.Dataset:
        """Eagerly load relationships needed for Dataset schema validation."""
        stmt = (
            select(self._model)
            .where(self._model.uuid == db_obj.uuid)
            .options(
                selectinload(self._model.project)
                .selectinload(models.Project.memberships)
                .selectinload(models.ProjectMember.user),
                selectinload(self._model.primary_site).selectinload(
                    models.Site.images
                ),
                selectinload(self._model.primary_recorder),
                selectinload(self._model.license),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def _get_dataset_recordings(
        self,
        session: AsyncSession,
        dataset: schemas.Dataset,
    ) -> list[models.Recording]:
        """Fetch all recordings associated with a dataset."""
        query = (
            select(models.Recording)
            .join(models.DatasetRecording)
            .where(models.DatasetRecording.dataset_id == dataset.id)
            .order_by(models.Recording.datetime, models.Recording.path)
        )
        result = await session.execute(query)
        return result.scalars().unique().all()

    async def create_from_data(
        self,
        session: AsyncSession,
        data: schemas.DatasetCreate | None = None,
        **kwargs,
    ) -> schemas.Dataset:
        """Create a dataset with eagerly loaded relationships."""
        from echoroo.api.common.utils import create_object

        # Create the dataset
        db_obj = await create_object(session, self._model, data, **kwargs)

        # Eagerly load relationships
        db_obj = await self._eager_load_relationships(session, db_obj)

        # Validate and cache
        obj = self._schema.model_validate(db_obj)
        self._update_cache(obj)
        return obj

    async def get(
        self,
        session: AsyncSession,
        pk: uuid.UUID,
        user: models.User | None = None,
    ) -> schemas.Dataset:
        from echoroo.api.common.utils import get_object

        db_user = await self._resolve_user(session, user)

        # Get the dataset object
        db_obj = await get_object(session, self._model, self._get_pk_condition(pk))

        # Eagerly load relationships
        db_obj = await self._eager_load_relationships(session, db_obj)

        # Validate
        data = self._schema.model_validate(db_obj)

        if not await can_view_dataset(session, data, db_user):
            raise exceptions.NotFoundError(f"Dataset with uuid {pk} not found")

        self._update_cache(data)
        return data

    async def get_many(
        self,
        session: AsyncSession,
        *,
        limit: int | None = 1000,
        offset: int | None = 0,
        filters: Sequence[Filter | ColumnExpressionArgument] | None = None,
        sort_by: ColumnExpressionArgument | str | None = "-created_on",
        user: models.User | None = None,
    ) -> tuple[Sequence[schemas.Dataset], int]:
        from echoroo.api.common.utils import get_objects

        db_user = await self._resolve_user(session, user)
        access_filters = await filter_datasets_by_access(session, db_user)

        combined_filters: list[Filter | ColumnExpressionArgument] = []
        if filters:
            combined_filters.extend(filters)
        combined_filters.extend(access_filters)

        # Get the database objects without validation
        db_objs, count = await get_objects(
            session,
            self._model,
            limit=limit,
            offset=offset,
            filters=combined_filters or None,
            sort_by=sort_by,
        )

        # Eagerly load relationships for all datasets
        datasets = []
        for db_obj in db_objs:
            db_obj = await self._eager_load_relationships(session, db_obj)
            datasets.append(self._schema.model_validate(db_obj))

        return datasets, count

    async def list_candidates(
        self,
        session: AsyncSession,
        *,
        audio_dir: Path | None = None,
    ) -> list[schemas.DatasetCandidate]:
        """List filesystem directories that are not yet registered as datasets."""
        if audio_dir is None:
            audio_dir = get_settings().audio_dir

        if not audio_dir.exists():
            return []

        result = await session.execute(select(models.Dataset.audio_dir))
        registered_dirs = {
            Path(value) for value in result.scalars() if value is not None
        }

        try:
            directories = [
                child
                for child in audio_dir.iterdir()
                if child.is_dir()
            ]
        except FileNotFoundError:
            return []

        directories.sort(key=lambda path: path.name.lower())

        candidates: list[schemas.DatasetCandidate] = []
        for directory in directories:
            try:
                relative_path = directory.relative_to(audio_dir)
            except ValueError:
                continue

            if any(
                registered == relative_path
                or registered.is_relative_to(relative_path)
                for registered in registered_dirs
            ):
                continue

            candidates.append(
                schemas.DatasetCandidate(
                    name=directory.name,
                    relative_path=relative_path,
                    absolute_path=directory,
                )
            )

        return candidates

    async def inspect_candidate(
        self,
        *,
        directory: Path,
        audio_dir: Path | None = None,
    ) -> schemas.DatasetCandidateInfo:
        """Inspect a candidate directory for nested folders and audio files."""
        if audio_dir is None:
            audio_dir = get_settings().audio_dir

        if directory.is_absolute():
            target_dir = directory
        else:
            target_dir = (audio_dir / directory).resolve()

        if not target_dir.exists() or not target_dir.is_dir():
            raise exceptions.NotFoundError(
                f"Directory {target_dir} does not exist."
            )

        try:
            relative_path = target_dir.relative_to(audio_dir)
        except ValueError as error:
            raise exceptions.InvalidDataError(
                "Only directories inside the audio root can be registered."
            ) from error

        has_nested = any(child.is_dir() for child in target_dir.iterdir())
        audio_files = files.get_audio_files_in_folder(
            target_dir,
            relative=False,
        )

        return schemas.DatasetCandidateInfo(
            relative_path=relative_path,
            absolute_path=target_dir,
            has_nested_directories=has_nested,
            audio_file_count=len(audio_files),
        )

    async def update(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        data: schemas.DatasetUpdate,
        audio_dir: Path | None = None,
        user: models.User | None = None,
    ) -> schemas.Dataset:
        """Update a dataset.

        Parameters
        ----------
        session
            The database session to use.
        obj
            The dataset to update.
        data
            The data to update the dataset with.
        audio_dir
            The root audio directory, by default None. If None, the root audio
            directory from the settings will be used.

        Returns
        -------
        dataset : schemas.Dataset

        Raises
        ------
        echoroo.exceptions.NotFoundError
            If no dataset with the given UUID exists.
        """
        if audio_dir is None:
            audio_dir = get_settings().audio_dir

        db_user = await self._resolve_user(session, user)

        if db_user is None or not await can_edit_dataset(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to update this dataset"
            )

        if (
            "project_id" in data.model_fields_set
            and data.project_id is not None
            and data.project_id != obj.project_id
        ):
            await self._ensure_project_manager(
                session,
                data.project_id,
                db_user,
            )

        if data.audio_dir is not None:
            if not data.audio_dir.is_relative_to(audio_dir):
                raise ValueError(
                    "The audio directory must be relative to the root audio "
                    "directory."
                    f"\n\tRoot audio directory: {audio_dir}"
                    f"\n\tAudio directory: {data.audio_dir}"
                )

            # If the audio directory has changed, update the path.
            data.audio_dir = data.audio_dir.relative_to(audio_dir)

        # Update the database object directly
        from echoroo.api.common.utils import update_object

        db_obj = await update_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
            data,
        )

        # Eagerly load relationships
        db_obj = await self._eager_load_relationships(session, db_obj)

        # Validate and cache
        updated = self._schema.model_validate(db_obj)
        self._update_cache(updated)
        return updated

    async def delete(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        *,
        user: models.User | None = None,
    ) -> schemas.Dataset:
        from echoroo.api.common.utils import delete_object

        db_user = await self._resolve_user(session, user)

        if db_user is None or not await can_delete_dataset(
            session, obj, db_user
        ):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to delete this dataset"
            )

        # Get the object first with eager loading
        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        db_obj = await self._eager_load_relationships(session, db_obj)

        # Validate before deletion
        to_delete = self._schema.model_validate(db_obj)

        # Delete the object
        await delete_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )

        # Remove from cache
        self._clear_from_cache(to_delete)

        return to_delete

    async def get_by_audio_dir(
        self,
        session: AsyncSession,
        audio_dir: Path,
    ) -> schemas.Dataset:
        """Get a dataset by audio directory.

        Parameters
        ----------
        session
            The database session to use.
        audio_dir
            The audio directory of the dataset to get.

        Returns
        -------
        dataset : schemas.Dataset

        Raises
        ------
        echoroo.exceptions.NotFoundError
            If no dataset with the given audio directory exists.
        """
        dataset = await common.get_object(
            session,
            models.Dataset,
            models.Dataset.audio_dir == audio_dir,
        )
        dataset = await self._eager_load_relationships(session, dataset)
        return schemas.Dataset.model_validate(dataset)

    async def get_by_name(
        self,
        session: AsyncSession,
        name: str,
    ) -> schemas.Dataset:
        """Get a dataset by name.

        Parameters
        ----------
        session
            The database session to use.
        name
            The name of the dataset to get.

        Returns
        -------
        dataset : schemas.Dataset

        Raises
        ------
        echoroo.exceptions.NotFoundError
            If no dataset with the given name exists.
        """
        dataset = await common.get_object(
            session,
            models.Dataset,
            models.Dataset.name == name,
        )
        dataset = await self._eager_load_relationships(session, dataset)
        return schemas.Dataset.model_validate(dataset)

    async def add_file(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        path: Path,
        date: datetime.date | None = None,
        time: datetime.time | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        time_expansion: float = 1.0,
        rights: str | None = None,
        audio_dir: Path | None = None,
    ) -> schemas.DatasetRecording:
        """Add a file to a dataset.

        This function adds a file to a dataset. The file is registered as a
        recording and is added to the dataset. If the file is already
        registered in the database, it is only added to the dataset.

        Parameters
        ----------
        session
            The database session to use.
        obj
            The dataset to add the file to.
        path
            The path to the audio file. This should be relative to the
            current working directory, or an absolute path.
        date
            The date of the recording.
        time
            The time of the recording.
        latitude
            The latitude of the recording site.
        longitude
            The longitude of the recording site.
        time_expansion
            Some recordings may be time expanded or time compressed. This
            value is the factor by which the recording is expanded or
            compressed. The default value is 1.0.
        rights
            A string describing the usage rights of the recording.
        audio_dir
            The root audio directory, by default None. If None, the root audio
            directory from the settings will be used.

        Returns
        -------
        recording : schemas.DatasetRecording
            The recording that was added to the dataset.

        Raises
        ------
        echoroo.exceptions.NotFoundError
            If the file does not exist.
        ValueError
            If the file is not part of the dataset audio directory.
        """
        if audio_dir is None:
            audio_dir = get_settings().audio_dir

        dataset_audio_dir = audio_dir / obj.audio_dir

        # Make sure the file is part of the dataset audio dir
        if not path.is_relative_to(dataset_audio_dir):
            raise ValueError(
                "The file is not part of the dataset audio directory."
            )

        try:
            recording = await recordings.get_by_path(
                session,
                path.relative_to(audio_dir),
            )
        except exceptions.NotFoundError:
            recording = await recordings.create(
                session,
                path=path,
                date=date,
                time=time,
                latitude=latitude,
                longitude=longitude,
                time_expansion=time_expansion,
                rights=rights,
                audio_dir=audio_dir,
            )

        return await self.add_recording(
            session,
            obj,
            recording,
        )

    async def add_recording(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        recording: schemas.Recording,
    ) -> schemas.DatasetRecording:
        """Add a recording to a dataset.

        Parameters
        ----------
        session
            The database session to use.
        obj
            The dataset to add the recording to.
        recording
            The recording to add to the dataset.

        Returns
        -------
        dataset_recording : schemas.DatasetRecording
            The dataset recording that was created.

        Raises
        ------
        ValueError
            If the recording is not part of the dataset audio directory.
        """
        if not recording.path.is_relative_to(obj.audio_dir):
            raise ValueError(
                "The recording is not part of the dataset audio directory."
            )

        dataset_recording = await common.create_object(
            session,
            models.DatasetRecording,
            data=schemas.DatasetRecordingCreate(
                path=recording.path.relative_to(obj.audio_dir),
            ),
            dataset_id=obj.id,
            recording_id=recording.id,
        )

        obj = obj.model_copy(
            update=dict(recording_count=obj.recording_count + 1)
        )
        self._update_cache(obj)
        return schemas.DatasetRecording.model_validate(dataset_recording)

    async def add_recordings(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        recordings: Sequence[schemas.Recording],
    ) -> list[schemas.DatasetRecording]:
        """Add recordings to a dataset.

        Use this function to efficiently add multiple recordings to a dataset.

        Parameters
        ----------
        session
            The database session to use.
        obj
            The dataset to add the recordings to.
        recordings
            The recordings to add to the dataset.
        """
        data = []
        for recording in recordings:
            if not recording.path.is_relative_to(obj.audio_dir):
                warnings.warn(
                    "The recording is not part of the dataset audio "
                    f"directory. \ndataset = {obj}\nrecording = {recording}",
                    stacklevel=2,
                )
                continue

            data.append(
                dict(
                    dataset_id=obj.id,
                    recording_id=recording.id,
                    path=recording.path.relative_to(obj.audio_dir),
                )
            )

        db_recordings = await common.create_objects_without_duplicates(
            session,
            models.DatasetRecording,
            data,
            key=lambda x: (x.get("dataset_id"), x.get("recording_id")),
            key_column=tuple_(
                models.DatasetRecording.dataset_id,
                models.DatasetRecording.recording_id,
            ),
        )

        # Reload the objects with the recording relationship eagerly loaded
        if db_recordings:
            recording_ids = [x.recording_id for x in db_recordings]
            db_recordings_with_rel, _ = await common.get_objects(
                session,
                models.DatasetRecording,
                filters=[
                    models.DatasetRecording.dataset_id == obj.id,
                    models.DatasetRecording.recording_id.in_(recording_ids),
                ],
                options=[selectinload(models.DatasetRecording.recording)],
                limit=None,
            )
        else:
            db_recordings_with_rel = []

        obj = obj.model_copy(
            update=dict(
                recording_count=obj.recording_count + len(db_recordings)
            )
        )
        self._update_cache(obj)
        return [
            schemas.DatasetRecording.model_validate(x) for x in db_recordings_with_rel
        ]

    async def get_recordings(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        *,
        limit: int = 1000,
        offset: int = 0,
        filters: Sequence[Filter] | None = None,
        sort_by: str | None = "-created_on",
    ) -> tuple[list[schemas.Recording], int]:
        """Get all recordings of a dataset.

        Parameters
        ----------
        session
            The database session to use.
        obj
            The ID of the dataset to get the recordings of.
        limit
            The maximum number of recordings to return, by default 1000.
            If set to -1, all recordings will be returned.
        offset
            The number of recordings to skip, by default 0.
        filters
            A list of filters to apply to the query, by default None.
        sort_by
            The column to sort the recordings by, by default None.

        Returns
        -------
        recordings : list[schemas.DatasetRecording]
        count : int
            The total number of recordings in the dataset.
        """
        database_recordings, count = await common.get_objects(
            session,
            models.Recording,
            limit=limit,
            offset=offset,
            filters=[
                DatasetFilter(eq=obj.uuid),
                *(filters or []),
            ],
            sort_by=sort_by,
        )
        return [
            schemas.Recording.model_validate(x) for x in database_recordings
        ], count

    async def get_state(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        audio_dir: Path | None = None,
    ) -> list[schemas.DatasetFile]:
        """Compute the state of the dataset recordings.

        The dataset directory is scanned for audio files and compared to the
        registered dataset recordings in the database. The following states are
        possible:

        - ``missing``: A file is registered in the database and but is missing.

        - ``registered``: A file is registered in the database and is present.

        - ``unregistered``: A file is not registered in the database but is
            present in the dataset directory.

        Parameters
        ----------
        session
            The database session to use.
        obj
            The dataset to get the state of.
        audio_dir
            The root audio directory, by default None. If None, the root audio
            directory from the settings will be used.

        Returns
        -------
        files : list[schemas.DatasetFile]
        """
        if audio_dir is None:
            audio_dir = get_settings().audio_dir

        # Get the files in the dataset directory.
        file_list = files.get_audio_files_in_folder(
            audio_dir / obj.audio_dir,
            relative=True,
        )

        # NOTE: Better to use this query than reusing the get_recordings
        # function because we don't need to retrieve all information about the
        # recordings.
        query = select(models.DatasetRecording.path).where(
            models.DatasetRecording.dataset_id == obj.id
        )
        result = await session.execute(query)
        db_files = [Path(path) for path in result.scalars().all()]

        existing_files = set(file_list) & set(db_files)
        missing_files = set(db_files) - set(file_list)
        unregistered_files = set(file_list) - set(db_files)

        ret = []
        for path in existing_files:
            ret.append(
                schemas.DatasetFile(
                    path=path,
                    state=schemas.FileState.REGISTERED,
                )
            )

        for path in missing_files:
            ret.append(
                schemas.DatasetFile(
                    path=path,
                    state=schemas.FileState.MISSING,
                )
            )

        for path in unregistered_files:
            ret.append(
                schemas.DatasetFile(
                    path=path,
                    state=schemas.FileState.UNREGISTERED,
                )
            )

        return ret

    async def from_soundevent(
        self,
        session: AsyncSession,
        data: data.Dataset,
        dataset_audio_dir: Path | None = None,
        audio_dir: Path | None = None,
        *,
        project_id: str,
        visibility: models.VisibilityLevel = models.VisibilityLevel.RESTRICTED,
    ) -> schemas.Dataset:
        """Create a dataset from a soundevent dataset.

        Parameters
        ----------
        session
            The database session to use.
        data
            The soundevent dataset.
        dataset_audio_dir
            The audio directory of the dataset, by default None. If None, the
            audio directory from the settings will be used.
        audio_dir
            The root audio directory, by default None. If None, the root audio
            directory from the settings will be used.

        Returns
        -------
        dataset : schemas.Dataset
            The dataset.
        """
        if dataset_audio_dir is None:
            dataset_audio_dir = get_settings().audio_dir

        creator = await ensure_system_user(session)

        obj = await self.create_from_data(
            session,
            audio_dir=dataset_audio_dir,
            name=data.name,
            description=data.description,
            uuid=data.uuid,
            created_on=data.created_on,
            created_by_id=creator.id,
            visibility=visibility,
            project_id=project_id,
        )

        for rec in data.recordings:
            recording = await recordings.from_soundevent(
                session,
                rec.model_copy(update=dict(path=dataset_audio_dir / rec.path)),
                audio_dir=audio_dir,
            )
            await self.add_recording(session, obj, recording)

        obj = obj.model_copy(update=dict(recording_count=len(data.recordings)))
        self._update_cache(obj)
        return obj

    async def to_soundevent(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        audio_dir: Path | None = None,
    ) -> data.Dataset:
        """Create a soundevent dataset from a dataset.

        Parameters
        ----------
        session
            The database session to use.
        obj
            The dataset.
        audio_dir
            The root audio directory, by default None. If None, the root audio
            directory from the settings will be used.

        Returns
        -------
        dataset : soundevent.Dataset
            The soundevent dataset.
        """
        if audio_dir is None:
            audio_dir = get_settings().audio_dir

        recs, _ = await self.get_recordings(session, obj, limit=-1)

        soundevent_recordings = [
            recordings.to_soundevent(r, audio_dir=audio_dir) for r in recs
        ]

        project_metadata: dict[str, str | None] | None = None
        if obj.project_id:
            project_metadata = {
                "project_id": obj.project_id,
                "project_name": getattr(obj.project, "project_name", None)
                if obj.project
                else None,
                "project_url": getattr(obj.project, "url", None)
                if obj.project
                else None,
                "project_description": getattr(obj.project, "description", None)
                if obj.project
                else None,
                "target_taxa": getattr(obj.project, "target_taxa", None)
                if obj.project
                else None,
                "admin_name": getattr(obj.project, "admin_name", None)
                if obj.project
                else None,
                "admin_email": getattr(obj.project, "admin_email", None)
                if obj.project
                else None,
            }

        dataset_metadata = {
            "note": obj.note,
            "doi": obj.doi,
            "primary_site_id": obj.primary_site_id,
        }

        def _compact(payload: dict[str, str | None]) -> dict[str, str]:
            return {k: v for k, v in payload.items() if v is not None}

        metadata_payload: dict[str, dict[str, str]] = {}
        if project_metadata:
            compact_project = _compact(project_metadata)
            if compact_project:
                metadata_payload["project"] = compact_project

        compact_dataset = _compact(dataset_metadata)
        if compact_dataset:
            metadata_payload["dataset"] = compact_dataset

        return data.Dataset(
            uuid=obj.uuid,
            name=obj.name,
            description=obj.description,
            created_on=obj.created_on,
            recordings=soundevent_recordings,
            metadata=metadata_payload or None,
        )

    async def create(
        self,
        session: AsyncSession,
        name: str,
        dataset_dir: Path,
        description: str | None = None,
        audio_dir: Path | None = None,
        *,
        user: models.User | schemas.SimpleUser,
        visibility: models.VisibilityLevel = models.VisibilityLevel.RESTRICTED,
        project_id: str,
        primary_site_id: str | None = None,
        primary_recorder_id: str | None = None,
        license_id: str | None = None,
        doi: str | None = None,
        note: str | None = None,
        gain: float | None = None,
    ) -> schemas.Dataset:
        """Create a dataset.

        This function will create a dataset and populate it with the audio
        files found in the given directory. It will look recursively for audio
        files within the directory.

        Parameters
        ----------
        session
            The database session to use.
        name
            The name of the dataset.
        dataset_dir
            The directory of the dataset.
        description
            The description of the dataset, by default None.
        audio_dir
            The root audio directory, by default None. If None, the root audio
            directory from the settings will be used.
        user
            The currently authenticated user creating the dataset.
        visibility
            Desired visibility level for the dataset.
        project_id
            Project identifier.
        primary_site_id
            Optional site identifier.
        primary_recorder_id
            Optional recorder identifier.
        license_id
            Optional license identifier.
        doi
            Optional DOI applied to the dataset.
        note
            Optional free-form note applied to the dataset.
        gain
            Optional recorder gain in dB.

        Returns
        -------
        dataset : schemas.Dataset

        Raises
        ------
        ValueError
            If a dataset with the given name or audio directory already exists.
        pydantic.ValidationError
            If the given audio directory does not exist.
        """
        if audio_dir is None:
            audio_dir = get_settings().audio_dir

        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "A valid user is required to create a dataset"
            )

        await self._ensure_project_manager(session, project_id, db_user)

        # Make sure the path is relative to the root audio directory.
        if not dataset_dir.is_relative_to(audio_dir):
            raise ValueError(
                "The audio directory must be relative to the root audio "
                "directory."
                f"\n\tRoot audio directory: {audio_dir}"
                f"\n\tAudio directory: {dataset_dir}"
            )

        # Validate the creation data.
        data = schemas.DatasetCreate(
            name=name,
            description=description,
            audio_dir=dataset_dir,
            visibility=visibility,
            project_id=project_id,
            primary_site_id=primary_site_id,
            primary_recorder_id=primary_recorder_id,
            license_id=license_id,
            doi=doi,
            note=note,
            gain=gain,
        )

        obj = await self.create_from_data(
            session,
            data.model_copy(
                update=dict(audio_dir=data.audio_dir.relative_to(audio_dir))
            ),
            created_by_id=db_user.id,
        )

        file_list = files.get_audio_files_in_folder(
            dataset_dir,
            relative=False,
        )

        if len(file_list) == 0:
            raise exceptions.InvalidDataError(
                "No audio files were found in the selected directory. "
                "Add WAV, MP3, or FLAC files before creating the dataset."
            )

        recording_list = await recordings.create_many(
            session,
            [dict(path=file) for file in file_list],
            audio_dir=audio_dir,
        )

        if recording_list is None:
            raise RuntimeError("No recordings were created.")

        dataset_recordigns = await self.add_recordings(
            session, obj, recording_list
        )

        # Inherit H3 index from primary site if available
        if primary_site_id:
            db_dataset = await session.get(models.Dataset, obj.id)
            if db_dataset and db_dataset.primary_site:
                h3_index = db_dataset.primary_site.h3_index
                # Update all recordings in this dataset with the site's H3 index
                for rec in recording_list:
                    db_rec = await session.get(models.Recording, rec.id)
                    if db_rec and not db_rec.h3_index:
                        db_rec.h3_index = h3_index
                await session.flush()

        obj = obj.model_copy(
            update=dict(recording_count=len(dataset_recordigns))
        )
        self._update_cache(obj)
        return obj

    async def to_dataframe(
        self,
        session: AsyncSession,
        dataset: schemas.Dataset,
    ) -> pd.DataFrame:
        """Convert a dataset to a pandas DataFrame.

        Generates a DataFrame containing information about the recordings in
        the dataset. The DataFrame includes the following columns: 'uuid',
        'hash', 'path', 'samplerate', 'duration', 'channels', 'time_expansion',
        'date', 'time', 'latitude', 'longitude', 'rights'.

        Owners, tags, and features receive special treatment. Owners are
        concatenated into a string with the format 'user1:user2:user3'. Each
        tag is added as a column with the name 'tag_<key>', and features as
        'feature_<name>'.

        Parameters
        ----------
        session
            The database session to use.
        dataset
            The dataset to convert to a DataFrame.

        Returns
        -------
        df : pandas.DataFrame
            The dataset as a DataFrame.

        Notes
        -----
        The encoding of the dataset as a DataFrame is not lossless. Notes are
        excluded from the DataFrame, and there is no way to recover all owner
        information from the concatenated string of usernames. For full dataset
        recovery, use the `to_soundevent` method instead, returning a sound
        event dataset that can be exported to a JSON file and later imported,
        recovering all information.
        """
        recordings, _ = await self.get_recordings(session, dataset, limit=-1)
        return pd.DataFrame(
            [
                dict(
                    uuid=rec.uuid,
                    hash=rec.hash,
                    path=rec.path.relative_to(dataset.audio_dir),
                    samplerate=rec.samplerate,
                    duration=rec.duration,
                    channels=rec.channels,
                    time_expansion=rec.time_expansion,
                    date=rec.date,
                    time=rec.time,
                    latitude=rec.latitude,
                    longitude=rec.longitude,
                    rights=rec.rights,
                    owners=":".join(
                        [
                            owner.name if owner.name else owner.username
                            for owner in rec.owners
                        ]
                    ),
                    **{f"tag_{tag.key}": tag.value for tag in rec.tags},
                    **{
                        f"feature_{feature.name}": feature.value
                        for feature in rec.features
                    },
                )
                for rec in recordings
            ]
        )

    async def import_dataset(
        self,
        session: AsyncSession,
        dataset: Path | BinaryIO | str,
        dataset_audio_dir: Path,
        audio_dir: Path | None = None,
    ) -> schemas.Dataset:
        db_dataset = await aoef.import_dataset(
            session,
            dataset,
            dataset_dir=dataset_audio_dir,
            audio_dir=audio_dir or Path.cwd(),
        )
        await session.commit()
        await session.refresh(db_dataset)
        db_dataset = await self._eager_load_relationships(session, db_dataset)
        return schemas.Dataset.model_validate(db_dataset)

    async def export_dataset(
        self,
        session: AsyncSession,
        dataset: schemas.Dataset,
        audio_dir: Path | None = None,
    ) -> AOEFObject:
        if audio_dir is None:
            audio_dir = get_settings().audio_dir

        dataset_audio_dir = audio_dir / dataset.audio_dir

        soundevent_dataset = await self.to_soundevent(
            session,
            dataset,
            audio_dir=audio_dir,
        )
        return to_aeof(soundevent_dataset, audio_dir=dataset_audio_dir)


    async def set_datetime_pattern(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        pattern_data: schemas.DatasetDatetimePatternUpdate,
        user: models.User | None = None,
    ) -> schemas.DatasetDatetimePattern:
        """Set or update the datetime parsing pattern for a dataset.

        Parameters
        ----------
        session
            The database session to use.
        obj
            The dataset to set the pattern for.
        pattern_data
            The pattern configuration.
        user
            The user performing the action (for permission check).

        Returns
        -------
        pattern : schemas.DatasetDatetimePattern
            The configured datetime pattern.
        """
        if user is not None:
            db_user = await self._resolve_user(session, user)
            if db_user is not None:
                db_obj = await session.get(models.Dataset, obj.id)
                if db_obj is not None:
                    await self._ensure_project_manager(
                        session, db_obj.project_id, db_user
                    )

        # Check if pattern already exists
        query = select(models.DatasetDatetimePattern).where(
            models.DatasetDatetimePattern.dataset_id == obj.id
        )
        result = await session.execute(query)
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing pattern
            existing.pattern = pattern_data.pattern
            existing.pattern_type = pattern_data.pattern_type
            existing.sample_filename = pattern_data.sample_filename
            existing.sample_result = None  # Will be computed on parse
            await session.flush()
            pattern = existing
        else:
            # Create new pattern
            pattern = models.DatasetDatetimePattern(
                dataset_id=obj.id,
                pattern=pattern_data.pattern,
                pattern_type=pattern_data.pattern_type,
                sample_filename=pattern_data.sample_filename,
            )
            session.add(pattern)
            await session.flush()

        return schemas.DatasetDatetimePattern.model_validate(pattern)

    async def parse_datetime_for_recordings(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        user: models.User | None = None,
    ) -> dict:
        """Parse datetime for all recordings in the dataset using the configured pattern.

        Parameters
        ----------
        session
            The database session to use.
        obj
            The dataset to parse.
        user
            The user performing the action (for permission check).

        Returns
        -------
        result : dict
            Summary with counts of success/failure.
        """
        import re
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo

        if user is not None:
            db_user = await self._resolve_user(session, user)
            if db_user is not None:
                db_obj = await session.get(models.Dataset, obj.id)
                if db_obj is not None and db_obj.project_id is not None:
                    await self._ensure_project_manager(
                        session, db_obj.project_id, db_user
                    )

        # Get the datetime pattern
        query = select(models.DatasetDatetimePattern).where(
            models.DatasetDatetimePattern.dataset_id == obj.id
        )
        result = await session.execute(query)
        pattern_config = result.scalar_one_or_none()

        if not pattern_config:
            raise exceptions.NotFoundError(
                "No datetime pattern configured for this dataset"
            )

        # Get all recordings for this dataset
        query = (
            select(models.Recording)
            .join(models.DatasetRecording)
            .where(models.DatasetRecording.dataset_id == obj.id)
        )
        result = await session.execute(query)
        recordings = result.scalars().unique().all()

        success_count = 0
        failure_count = 0

        for rec in recordings:
            try:
                # Use full filename (with extension) if pattern contains a dot
                # Otherwise use just the stem
                if "." in pattern_config.pattern:
                    filename = Path(rec.path).name
                else:
                    filename = Path(rec.path).stem

                if pattern_config.pattern_type == models.DatetimePatternType.STRPTIME:
                    # Use strptime
                    parsed_dt = dt.strptime(filename, pattern_config.pattern)
                else:
                    # Use regex
                    match = re.search(pattern_config.pattern, filename)
                    if not match:
                        raise ValueError(f"Pattern did not match filename: {filename}")
                    # Assume the pattern captures datetime components
                    # This is a simplified implementation
                    groups = match.groups()
                    if len(groups) >= 6:
                        year, month, day, hour, minute, second = groups[:6]
                        parsed_dt = dt(
                            int(year), int(month), int(day),
                            int(hour), int(minute), int(second)
                        )
                    else:
                        raise ValueError("Regex pattern must capture at least 6 groups (Y,M,D,H,M,S)")

                # Add timezone information (assume Japan timezone)
                # The parsed datetime is treated as local time (JST)
                jst_dt = parsed_dt.replace(tzinfo=ZoneInfo("Asia/Tokyo"))

                # Update recording
                rec.datetime = jst_dt
                rec.datetime_parse_status = models.DatetimeParseStatus.SUCCESS
                rec.datetime_parse_error = None
                success_count += 1

            except Exception as e:
                rec.datetime_parse_status = models.DatetimeParseStatus.FAILED
                rec.datetime_parse_error = str(e)
                failure_count += 1

        await session.flush()

        return {
            "total": len(recordings),
            "success": success_count,
            "failure": failure_count,
        }

    async def get_datetime_parse_status(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        user: models.User | None = None,
    ) -> dict:
        """Get the datetime parsing status summary for a dataset.

        Parameters
        ----------
        session
            The database session to use.
        obj
            The dataset.
        user
            The user requesting (for permission check).

        Returns
        -------
        status : dict
            Summary of parse status.
        """
        if user is not None:
            db_user = await self._resolve_user(session, user)
            if db_user is not None:
                db_dataset = await self.get(session, obj.uuid, user=db_user)
                if not await can_view_dataset(session, db_dataset, db_user):
                    raise exceptions.PermissionDeniedError(
                        "You don't have permission to view this dataset"
                    )

        # Get status counts
        query = (
            select(
                models.Recording.datetime_parse_status,
                sa.func.count(models.Recording.id).label("count"),
            )
            .join(models.DatasetRecording)
            .where(models.DatasetRecording.dataset_id == obj.id)
            .group_by(models.Recording.datetime_parse_status)
        )
        result = await session.execute(query)
        status_counts = {row[0].value: row[1] for row in result.all()}

        return {
            "pending": status_counts.get("pending", 0),
            "success": status_counts.get("success", 0),
            "failed": status_counts.get("failed", 0),
        }

    async def get_filename_samples(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        limit: int = 20,
        user: models.User | None = None,
    ) -> list[str]:
        """Get a sample of recording filenames from a dataset.

        Parameters
        ----------
        session
            The database session to use.
        obj
            The dataset.
        limit
            Maximum number of filenames to return.
        user
            The user requesting (for permission check).

        Returns
        -------
        filenames : list[str]
            List of recording filenames (just the filename, not full path).
        """
        if user is not None:
            db_user = await self._resolve_user(session, user)
            if db_user is not None:
                db_dataset = await self.get(session, obj.uuid, user=db_user)
                if not await can_view_dataset(session, db_dataset, db_user):
                    raise exceptions.PermissionDeniedError(
                        "You don't have permission to view this dataset"
                    )

        # Get recording paths
        query = (
            select(models.Recording.path)
            .join(models.DatasetRecording)
            .where(models.DatasetRecording.dataset_id == obj.id)
            .limit(limit)
        )
        result = await session.execute(query)
        paths = [row[0] for row in result.all()]

        # Extract just the filename from each path
        filenames = [Path(path).name for path in paths]
        return filenames

    async def export_camtrapdp_deployments(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        user: models.User | None = None,
    ) -> pd.DataFrame:
        """Export dataset as CamtrapDP deployments.csv.

        Each dataset with a primary site becomes one deployment row.
        The deployment period is calculated from the min/max datetime
        of all recordings in the dataset.

        Parameters
        ----------
        session
            Database session.
        obj
            Dataset to export.
        user
            User requesting the export (for permission checks).

        Returns
        -------
        pd.DataFrame
            CamtrapDP deployments.csv formatted dataframe.
        """
        # Permission check
        if user is not None:
            db_user = await common.get_object(
                session,
                models.User,
                models.User.id == user.id,
            )
            db_dataset = await self.get(session, obj.uuid, user=db_user)
            if not await can_view_dataset(session, db_dataset, db_user):
                raise exceptions.PermissionDeniedError(
                    "You don't have permission to export this dataset"
                )

        # Get all recordings with datetime
        query = (
            select(models.Recording)
            .join(models.DatasetRecording)
            .where(models.DatasetRecording.dataset_id == obj.id)
            .where(models.Recording.datetime.isnot(None))
        )
        result = await session.execute(query)
        recordings = result.scalars().unique().all()

        if not recordings:
            # Return empty dataframe with correct bioacoustics schema
            return pd.DataFrame(columns=[
                "deploymentID",
                "locationID",
                "locationName",
                "latitude",
                "longitude",
                "coordinateUncertainty",
                "elevation",
                "deploymentStart",
                "deploymentEnd",
                "setupBy",
                "deviceID",
                "deviceModel",
                "devicePlatform",
                "deviceDelay",
                "deviceHeight",
                "deviceDepth",
                "deviceTilt",
                "deviceHeading",
                "recordingSchedule",
                "detectionDistance",
                "baitUse",
                "locationType",
                "habitat",
                "deploymentGroups",
                "deploymentTags",
                "deploymentComments",
                "h3Index",
            ])

        # Calculate deployment period
        datetimes = [rec.datetime for rec in recordings if rec.datetime]
        deployment_start = min(datetimes) if datetimes else None
        deployment_end = max(datetimes) if datetimes else None

        # Get site information
        site = obj.primary_site
        latitude = None
        longitude = None
        h3_index = None

        if site and site.h3_index:
            h3_index = site.h3_index
            # Convert H3 to lat/lon
            try:
                lat, lng = h3.cell_to_latlng(h3_index)
                latitude = lat
                longitude = lng
            except Exception:
                pass

        # Get recorder information from dataset
        recorder = obj.primary_recorder
        device_id = recorder.recorder_id if recorder else None
        device_model = recorder.recorder_name if recorder else None

        coordinate_uncertainty = None
        if h3_index:
            try:
                # Use the circumradius (outer radius) of the hexagon as coordinate uncertainty
                # This represents the maximum distance from the center to any vertex
                coordinate_uncertainty = h3.cell_area(h3_index, unit='m2') ** 0.5 / (3 ** 0.5 / 2)
                # Simpler approach: use great_circle_distance to approximate
                # Get the hexagon boundary and calculate the circumradius
                boundary = h3.cell_to_boundary(h3_index)
                if boundary:
                    center_lat, center_lng = h3.cell_to_latlng(h3_index)
                    # Calculate distance from center to first vertex (all vertices equidistant)
                    vertex_lat, vertex_lng = boundary[0]
                    coordinate_uncertainty = h3.great_circle_distance(
                        (center_lat, center_lng),
                        (vertex_lat, vertex_lng),
                        unit='m'
                    )
            except Exception:
                pass

        # Create deployment row (bioacoustics format)
        deployment_data = {
            "deploymentID": str(obj.uuid),
            "locationID": site.site_id if site else None,
            "locationName": site.site_name if site else None,
            "latitude": latitude,
            "longitude": longitude,
            "coordinateUncertainty": coordinate_uncertainty,
            "elevation": None,  # Not tracked
            "deploymentStart": deployment_start.isoformat() if deployment_start else None,
            "deploymentEnd": deployment_end.isoformat() if deployment_end else None,
            "setupBy": None,  # Not tracked
            "deviceID": device_id,
            "deviceModel": device_model,
            "devicePlatform": None,  # Not tracked
            "deviceDelay": None,  # Not tracked
            "deviceHeight": None,  # Not tracked
            "deviceDepth": None,  # Not applicable for terrestrial audio
            "deviceTilt": None,  # Not tracked
            "deviceHeading": None,  # Not tracked
            "recordingSchedule": None,  # Not tracked
            "detectionDistance": None,  # Not applicable for audio
            "baitUse": None,  # Not applicable for audio
            "locationType": None,  # Could map from site metadata
            "habitat": None,  # Could map from site metadata
            "deploymentGroups": None,
            "deploymentTags": None,
            "deploymentComments": obj.description,
            "h3Index": h3_index,  # Extension field
        }

        return pd.DataFrame([deployment_data])

    async def export_camtrapdp_media(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        user: models.User | None = None,
    ) -> pd.DataFrame:
        """Export dataset recordings as CamtrapDP media.csv.

        Each recording becomes one media row.

        Parameters
        ----------
        session
            Database session.
        obj
            Dataset to export.
        user
            User requesting the export (for permission checks).

        Returns
        -------
        pd.DataFrame
            CamtrapDP media.csv formatted dataframe.
        """
        # Permission check
        if user is not None:
            db_user = await common.get_object(
                session,
                models.User,
                models.User.id == user.id,
            )
            db_dataset = await self.get(session, obj.uuid, user=db_user)
            if not await can_view_dataset(session, db_dataset, db_user):
                raise exceptions.PermissionDeniedError(
                    "You don't have permission to export this dataset"
                )

        # Get all recordings
        query = (
            select(models.Recording)
            .join(models.DatasetRecording)
            .where(models.DatasetRecording.dataset_id == obj.id)
            .order_by(models.Recording.datetime, models.Recording.path)
        )
        result = await session.execute(query)
        recordings = result.scalars().unique().all()

        if not recordings:
            # Return empty dataframe with correct bioacoustics schema
            return pd.DataFrame(columns=[
                "mediaID",
                "deploymentID",
                "captureMethod",
                "timestamp",
                "duration",
                "filePath",
                "filePublic",
                "fileName",
                "fileMediatype",
                "exifData",
                "bitDepth",
                "samplingFrequency",
                "gain",
                "channels",
                "favorite",
                "mediaComments",
            ])

        # Create media rows (bioacoustics format)
        media_rows = []
        for rec in recordings:
            # Generate mediaID from recording UUID
            media_id = str(rec.uuid).replace("-", "")[:20]

            # Determine file mediatype from extension
            file_ext = Path(rec.path).suffix.lower()
            if file_ext == ".wav":
                mediatype = "audio/wav"
            elif file_ext == ".mp3":
                mediatype = "audio/mpeg"
            elif file_ext == ".flac":
                mediatype = "audio/flac"
            else:
                mediatype = f"audio/{file_ext[1:]}" if file_ext else "audio/wav"

            media_row = {
                "mediaID": media_id,
                "deploymentID": str(obj.uuid),
                "captureMethod": None,  # Empty by default
                "timestamp": rec.datetime.isoformat() if rec.datetime else None,
                "duration": int(rec.duration) if rec.duration else None,
                "filePath": str(rec.path),
                "filePublic": "TRUE",  # Uppercase for bioacoustics format
                "fileName": Path(rec.path).name,
                "fileMediatype": mediatype,
                "exifData": None,
                "bitDepth": rec.bit_depth,
                "samplingFrequency": rec.samplerate,
                "gain": None,  # Not tracked
                "channels": rec.channels,
                "favorite": None,
                "mediaComments": None,
            }
            media_rows.append(media_row)

        return pd.DataFrame(media_rows)

    async def get_overview_stats(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        user: models.User | None = None,
    ) -> schemas.DatasetOverviewStats:
        """Aggregate high level stats for the dataset overview."""
        if user is not None:
            db_user = await common.get_object(
                session,
                models.User,
                models.User.id == user.id,
            )
            db_dataset = await self.get(session, obj.uuid, user=db_user)
            if not await can_view_dataset(session, db_dataset, db_user):
                raise exceptions.PermissionDeniedError(
                    "You don't have permission to view this dataset"
                )

        # Aggregate recording locations
        site_query = (
            select(
                models.Recording.h3_index,
                models.Recording.latitude,
                models.Recording.longitude,
                sa.func.count(models.Recording.id),
            )
            .join(models.DatasetRecording)
            .where(models.DatasetRecording.dataset_id == obj.id)
            .group_by(
                models.Recording.h3_index,
                models.Recording.latitude,
                models.Recording.longitude,
            )
        )
        site_rows = (await session.execute(site_query)).all()
        recording_sites: list[schemas.DatasetRecordingSite] = []
        primary_h3 = (
            obj.primary_site.h3_index if obj.primary_site and obj.primary_site.h3_index else None
        )
        primary_label = (
            obj.primary_site.site_name or obj.primary_site.site_id
            if obj.primary_site
            else None
        )

        for h3_index, lat, lng, count in site_rows:
            latitude = lat
            longitude = lng
            if (latitude is None or longitude is None) and h3_index:
                try:
                    latitude, longitude = h3.cell_to_latlng(h3_index)
                except Exception:
                    latitude = longitude = None
            if latitude is None or longitude is None:
                continue
            label = primary_label if primary_h3 and h3_index == primary_h3 else None
            recording_sites.append(
                schemas.DatasetRecordingSite(
                    h3_index=h3_index,
                    latitude=latitude,
                    longitude=longitude,
                    recording_count=count,
                    label=label,
                )
            )

        # Build calendar buckets, heatmap data, and timeline segments
        calendar_query = (
            select(
                models.Recording.uuid,
                models.Recording.path,
                models.Recording.datetime,
                models.Recording.date,
                models.Recording.time,
                models.Recording.duration,
            )
            .join(models.DatasetRecording)
            .where(models.DatasetRecording.dataset_id == obj.id)
        )
        calendar_rows = (await session.execute(calendar_query)).all()
        bucket_counts: dict[datetime.date, int] = defaultdict(int)
        heatmap_data: dict[tuple[datetime.date, int], dict] = defaultdict(
            lambda: {"count": 0, "duration": 0.0}
        )
        timeline_segments: list[schemas.DatasetRecordingTimelineSegment] = []

        for rec_uuid, rec_path, dt_value, date_value, time_value, duration in calendar_rows:
            bucket_date: datetime.date | None = None
            bucket_hour: int | None = None
            start_dt: datetime.datetime | None = None

            if dt_value is not None:
                bucket_date = dt_value.date()
                bucket_hour = dt_value.hour
                start_dt = dt_value
            elif date_value is not None:
                bucket_date = date_value
                if time_value is not None:
                    bucket_hour = time_value.hour
                    start_dt = datetime.datetime.combine(date_value, time_value)

            if bucket_date is None:
                continue

            bucket_counts[bucket_date] += 1
            if bucket_hour is not None:
                cell = heatmap_data[(bucket_date, bucket_hour)]
                cell["count"] += 1
                cell["duration"] += (duration or 0) / 60.0

            # Build timeline segment if we have precise start time
            if start_dt is not None and duration is not None:
                end_dt = start_dt + datetime.timedelta(seconds=duration)
                timeline_segments.append(
                    schemas.DatasetRecordingTimelineSegment(
                        recording_uuid=str(rec_uuid),
                        start=start_dt,
                        end=end_dt,
                        path=str(rec_path),
                    )
                )

        recording_calendar = [
            schemas.DatasetRecordingCalendarBucket(date=date, count=count)
            for date, count in sorted(bucket_counts.items())
        ]
        recording_heatmap = [
            schemas.DatasetRecordingHeatmapCell(
                date=key[0],
                hour=key[1],
                count=val["count"],
                duration_minutes=val["duration"],
            )
            for key, val in sorted(heatmap_data.items())
        ]
        # Sort timeline by start time
        timeline_segments.sort(key=lambda x: x.start)

        duration_query = (
            select(sa.func.sum(models.Recording.duration))
            .join(models.DatasetRecording)
            .where(models.DatasetRecording.dataset_id == obj.id)
        )
        total_duration = (await session.execute(duration_query)).scalar()

        # Get the absolute path from audio_dir
        absolute_path = Path(obj.audio_dir) if obj.audio_dir else Path(".")

        # Check for nested directories and count audio files
        has_nested = False
        audio_file_count = 0
        if absolute_path.exists():
            for entry in absolute_path.iterdir():
                if entry.is_dir():
                    has_nested = True
                    break
            audio_file_count = len(files.find_audio_files(absolute_path, recursive=True))

        return schemas.DatasetOverviewStats(
            recording_sites=recording_sites,
            recording_calendar=recording_calendar,
            recording_heatmap=recording_heatmap,
            recording_timeline=timeline_segments,
            total_duration_seconds=float(total_duration) if total_duration is not None else None,
            absolute_path=absolute_path,
            has_nested_directories=has_nested,
            audio_file_count=audio_file_count,
        )

    async def build_bioacoustics_export(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        *,
        include_audio: bool = False,
        user: models.User | None = None,
        audio_dir: Path | None = None,
    ) -> tuple[str, int]:
        """Create a ZIP file and return its path and size.

        Returns:
            tuple of (temp_file_path, file_size_bytes)
        """
        if user is not None:
            db_user = await common.get_object(
                session,
                models.User,
                models.User.id == user.id,
            )
            db_dataset = await self.get(session, obj.uuid, user=db_user)
            if not await can_view_dataset(session, db_dataset, db_user):
                raise exceptions.PermissionDeniedError(
                    "You don't have permission to export this dataset"
                )

        deployments_df = await self.export_camtrapdp_deployments(
            session,
            obj,
            user=user,
        )
        media_df = await self.export_camtrapdp_media(
            session,
            obj,
            user=user,
        )

        # Use a temporary file to create the ZIP
        # This avoids loading everything into memory
        import logging
        import time
        logger = logging.getLogger(__name__)

        zip_start = time.time()
        temp_fd, temp_path = tempfile.mkstemp(suffix='.zip')
        logger.info(f"[PERF] Starting ZIP creation for dataset {obj.uuid}")

        try:
            with os.fdopen(temp_fd, 'wb') as temp_file:
                with ZipFile(temp_file, 'w', ZIP_STORED, allowZip64=True) as zipf:
                    # Add CSV files with compression (they're small)
                    zipf.writestr(
                        "deployments.csv",
                        deployments_df.to_csv(index=False).encode("utf-8"),
                        compress_type=ZIP_DEFLATED,
                    )
                    zipf.writestr(
                        "media.csv",
                        media_df.to_csv(index=False).encode("utf-8"),
                        compress_type=ZIP_DEFLATED,
                    )

                    if include_audio:
                        base_audio_dir = audio_dir or get_settings().audio_dir
                        base_audio_path = Path(base_audio_dir)
                        dataset_root = Path(obj.audio_dir)

                        # Get recording paths
                        query = (
                            select(models.Recording.path)
                            .join(models.DatasetRecording)
                            .where(models.DatasetRecording.dataset_id == obj.id)
                            .order_by(models.Recording.datetime, models.Recording.path)
                        )
                        result = await session.execute(query)
                        recording_paths = result.scalars().all()

                        # Prepare file info list: (absolute_path, arcname)
                        file_info_list: list[tuple[Path, str]] = []
                        for rec_path in recording_paths:
                            relative_path = Path(rec_path)
                            absolute_path = base_audio_path / relative_path

                            try:
                                relative_audio_path = relative_path.relative_to(dataset_root)
                            except ValueError:
                                relative_audio_path = relative_path

                            arcname = str(Path("Audio") / relative_audio_path)
                            file_info_list.append((absolute_path, arcname))

                        # Parallel file reading function
                        def read_file_sync(file_path: Path, arcname: str) -> tuple[str, bytes] | None:
                            """Read a file synchronously, return (arcname, content) or None."""
                            try:
                                if not file_path.exists():
                                    return None
                                return (arcname, file_path.read_bytes())
                            except Exception as e:
                                logger.warning(f"Failed to read file {file_path}: {e}")
                                return None

                        # Read files in parallel using ThreadPoolExecutor
                        # Batch processing to limit memory usage
                        BATCH_SIZE = 50
                        MAX_WORKERS = 8

                        logger.info(f"[PERF] Starting parallel read of {len(file_info_list)} audio files")
                        read_start = time.time()

                        for batch_start in range(0, len(file_info_list), BATCH_SIZE):
                            batch = file_info_list[batch_start:batch_start + BATCH_SIZE]

                            # Read batch in parallel using ThreadPoolExecutor
                            loop = asyncio.get_running_loop()
                            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                                tasks = [
                                    loop.run_in_executor(executor, read_file_sync, path, arcname)
                                    for path, arcname in batch
                                ]
                                batch_results = await asyncio.gather(*tasks)

                            # Write batch results to ZIP (sequential, as ZipFile is not thread-safe)
                            for result in batch_results:
                                if result is not None:
                                    arcname, content = result
                                    zipf.writestr(arcname, content, compress_type=ZIP_STORED)

                        read_elapsed = time.time() - read_start
                        logger.info(f"[PERF] Parallel file reading completed in {read_elapsed:.2f} seconds")

            zip_elapsed = time.time() - zip_start
            file_size = os.path.getsize(temp_path)
            logger.info(f"[PERF] ZIP creation completed in {zip_elapsed:.2f} seconds, size: {file_size / (1024*1024):.2f} MB")

            # Return the temp file path and size
            # The caller is responsible for cleaning up the file after streaming
            return temp_path, file_size

        except Exception:
            # Clean up on error
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            raise


datasets = DatasetAPI()
