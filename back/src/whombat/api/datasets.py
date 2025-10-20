"""API functions for interacting with datasets."""

import datetime
import uuid
import warnings
from pathlib import Path
from typing import BinaryIO, Sequence

import pandas as pd
from soundevent import data
from soundevent.io.aoef import AOEFObject, to_aeof
from sqlalchemy import select, tuple_
from sqlalchemy.sql import ColumnExpressionArgument
from sqlalchemy.ext.asyncio import AsyncSession

from whombat import exceptions, models, schemas
from whombat.api import common
from whombat.api.common import BaseAPI
from whombat.api.common.permissions import (
    can_delete_dataset,
    can_edit_dataset,
    can_manage_restricted_dataset,
    can_view_dataset,
    filter_datasets_by_access,
)
from whombat.api.io import aoef
from whombat.api.users import ensure_system_user
from whombat.api.recordings import recordings
from whombat.core import files
from whombat.filters.base import Filter
from whombat.filters.recordings import DatasetFilter
from whombat.system import get_settings

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
    ]
):
    _model = models.Dataset
    _schema = schemas.Dataset

    async def _resolve_user(
        self,
        session: AsyncSession,
        user: models.User | schemas.SimpleUser | None,
    ) -> models.User | None:
        if user is None:
            return None
        if isinstance(user, models.User):
            return user
        db_user = await session.get(models.User, user.id)
        if db_user is None:
            raise exceptions.NotFoundError(
                f"User with id {user.id} not found"
            )
        return db_user

    async def get(
        self,
        session: AsyncSession,
        pk: uuid.UUID,
        user: models.User | None = None,
    ) -> schemas.Dataset:
        db_user = await self._resolve_user(session, user)
        data = await super().get(session, pk)

        if not await can_view_dataset(session, data, db_user):
            raise exceptions.NotFoundError(f"Dataset with uuid {pk} not found")

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
        db_user = await self._resolve_user(session, user)
        access_filters = await filter_datasets_by_access(session, db_user)

        combined_filters: list[Filter | ColumnExpressionArgument] = []
        if filters:
            combined_filters.extend(filters)
        combined_filters.extend(access_filters)

        return await super().get_many(
            session,
            limit=limit,
            offset=offset,
            filters=combined_filters or None,
            sort_by=sort_by,
        )

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
        whombat.exceptions.NotFoundError
            If no dataset with the given UUID exists.
        """
        if audio_dir is None:
            audio_dir = get_settings().audio_dir

        db_user = await self._resolve_user(session, user)

        if db_user is None or not await can_edit_dataset(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to update this dataset"
            )

        target_visibility = obj.visibility
        if "visibility" in data.model_fields_set:
            target_visibility = data.visibility or obj.visibility

        target_group_id = obj.owner_group_id
        if "owner_group_id" in data.model_fields_set:
            target_group_id = data.owner_group_id

        if (
            target_visibility == models.VisibilityLevel.RESTRICTED
            and target_group_id is None
        ):
            raise exceptions.InvalidDataError(
                "Restricted visibility requires owner_group_id to be set"
            )

        if (
            db_user is not None
            and target_visibility == models.VisibilityLevel.RESTRICTED
            and target_group_id is not None
        ):
            allowed = await can_manage_restricted_dataset(
                session,
                target_group_id,
                db_user,
            )
            if not allowed:
                raise exceptions.PermissionDeniedError(
                    "You must be a manager of the selected group"
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

        return await super().update(session, obj, data)

    async def delete(
        self,
        session: AsyncSession,
        obj: schemas.Dataset,
        *,
        user: models.User | None = None,
    ) -> schemas.Dataset:
        db_user = await self._resolve_user(session, user)

        if db_user is None or not await can_delete_dataset(
            session, obj, db_user
        ):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to delete this dataset"
            )

        return await super().delete(session, obj)

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
        whombat.exceptions.NotFoundError
            If no dataset with the given audio directory exists.
        """
        dataset = await common.get_object(
            session,
            models.Dataset,
            models.Dataset.audio_dir == audio_dir,
        )
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
        whombat.exceptions.NotFoundError
            If no dataset with the given name exists.
        """
        dataset = await common.get_object(
            session,
            models.Dataset,
            models.Dataset.name == name,
        )
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
        whombat.exceptions.NotFoundError
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

        obj = obj.model_copy(
            update=dict(
                recording_count=obj.recording_count + len(db_recordings)
            )
        )
        self._update_cache(obj)
        return [
            schemas.DatasetRecording.model_validate(x) for x in db_recordings
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
            visibility=models.VisibilityLevel.PRIVATE,
            owner_group_id=None,
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

        return data.Dataset(
            uuid=obj.uuid,
            name=obj.name,
            description=obj.description,
            created_on=obj.created_on,
            recordings=soundevent_recordings,
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
        visibility: models.VisibilityLevel = models.VisibilityLevel.PRIVATE,
        owner_group_id: int | None = None,
        **kwargs,
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
        owner_group_id
            Owning group when visibility is "restricted".
        **kwargs
            Additional keyword arguments to pass to the creation function.

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

        if (
            visibility == models.VisibilityLevel.RESTRICTED
            and owner_group_id is None
        ):
            raise exceptions.InvalidDataError(
                "Restricted visibility requires owner_group_id to be set"
            )

        if (
            visibility == models.VisibilityLevel.RESTRICTED
            and owner_group_id is not None
        ):
            allowed = await can_manage_restricted_dataset(
                session,
                owner_group_id,
                db_user,
            )
            if not allowed:
                raise exceptions.PermissionDeniedError(
                    "You must be a manager of the selected group to create a restricted dataset"
                )

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
            owner_group_id=owner_group_id,
        )

        obj = await self.create_from_data(
            session,
            data.model_copy(
                update=dict(audio_dir=data.audio_dir.relative_to(audio_dir))
            ),
            created_by_id=db_user.id,
            **kwargs,
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


datasets = DatasetAPI()
