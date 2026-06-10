"""Export service for CamtrapDP-style dataset export."""

import asyncio
import csv
import io
import json
import zipfile
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.repositories.dataset import DatasetRepository
from echoroo.repositories.recording import RecordingRepository
from echoroo.services.audio import AudioService
from echoroo.services.camtrap import deployment_id, media_id
from echoroo.services.detection_export import DetectionExportService
from echoroo.services.h3_utils import h3_to_center


class ExportService:
    """Service for exporting datasets in CamtrapDP format."""

    def __init__(
        self,
        db: AsyncSession,
        audio_service: AudioService | None = None,
    ) -> None:
        """Initialize service.

        Args:
            db: Database session
            audio_service: Optional audio service for file access
        """
        self.db = db
        self.dataset_repo = DatasetRepository(db)
        self.recording_repo = RecordingRepository(db)
        self.audio_service = audio_service

    async def generate_deployments_csv(self, dataset_id: UUID) -> str:
        """Generate deployments.csv content.

        CamtrapDP deployments format:
        - deploymentID: Unique deployment identifier
        - locationID: Site/location identifier
        - locationName: Site name
        - latitude: GPS latitude
        - longitude: GPS longitude
        - deploymentStart: Start datetime
        - deploymentEnd: End datetime
        - setupBy: Person who set up
        - cameraID: Recorder ID
        - h3_cell_id: Effective (possibly generalized) H3 cell id (FR-086 parity)
        - h3_resolution: Effective H3 resolution of h3_cell_id
        - withheld_reason: Reason the location was clamped (or empty)

        Args:
            dataset_id: Dataset UUID

        Returns:
            CSV content as string

        Raises:
            ValueError: If dataset not found
        """
        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if not dataset:
            raise ValueError("Dataset not found")

        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(
            [
                "deploymentID",
                "locationID",
                "locationName",
                "latitude",
                "longitude",
                "deploymentStart",
                "deploymentEnd",
                "setupBy",
                "cameraID",
                # FR-086 trailing extensions — same convention as the
                # observation export (detection_export / annotation_set_export).
                "h3_cell_id",
                "h3_resolution",
                "withheld_reason",
            ]
        )

        # Get recordings to determine date range
        recordings, _ = await self.recording_repo.list_by_dataset(
            dataset_id, page=1, page_size=1, sort_by="datetime", sort_order="asc"
        )
        first_recording = recordings[0] if recordings else None

        recordings_desc, _ = await self.recording_repo.list_by_dataset(
            dataset_id, page=1, page_size=1, sort_by="datetime", sort_order="desc"
        )
        last_recording = recordings_desc[0] if recordings_desc else None

        # Get site info. The location columns honour the project's location
        # generalization: lat/long are derived from the EFFECTIVE (possibly
        # coarsened) H3 cell so a Restricted/obscured site never leaks a precise
        # center and lat/long stays consistent with the emitted h3_cell_id.
        site = dataset.site
        lat = None
        lng = None
        effective_cell: str | None = None
        effective_resolution: int | None = None
        withheld_reason: str | None = None
        if site and site.h3_index_member:
            (
                effective_cell,
                effective_resolution,
                withheld_reason,
            ) = DetectionExportService.compute_export_location_cell(
                project=dataset.project,
                site_h3_index=site.h3_index_member,
                site_resolution=site.h3_index_member_resolution,
            )
            if effective_cell:
                lat, lng = h3_to_center(effective_cell)

        writer.writerow(
            [
                # Canonical CamtrapDP join key (approved 2026-06-09):
                # deploymentID == str(dataset.id), shared with every observation
                # export so the deployments<->observations join is consistent.
                deployment_id(dataset.id),
                str(site.id) if site else "",
                site.name if site else "",
                lat if lat else "",
                lng if lng else "",
                (
                    first_recording.datetime.isoformat()
                    if first_recording and first_recording.datetime
                    else ""
                ),
                (
                    last_recording.datetime.isoformat()
                    if last_recording and last_recording.datetime
                    else ""
                ),
                (
                    dataset.created_by.display_name or dataset.created_by.email
                    if dataset.created_by
                    else ""
                ),
                dataset.recorder_id or "",
                # FR-086 trailing extensions (empty when the deployment has no
                # site / no H3 index).
                effective_cell or "",
                str(effective_resolution) if effective_resolution is not None else "",
                withheld_reason or "",
            ]
        )

        return output.getvalue()

    async def generate_media_csv(self, dataset_id: UUID) -> str:
        """Generate media.csv content.

        CamtrapDP media format:
        - mediaID: Unique media identifier
        - deploymentID: Reference to deployment
        - captureMethod: How media was captured
        - timestamp: Capture datetime
        - filePath: Relative path to file
        - filePublic: Is file publicly available
        - fileName: Original filename
        - fileMediatype: MIME type
        - exifData: JSON of technical metadata

        Args:
            dataset_id: Dataset UUID

        Returns:
            CSV content as string

        Raises:
            ValueError: If dataset not found
        """
        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if not dataset:
            raise ValueError("Dataset not found")

        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(
            [
                "mediaID",
                "deploymentID",
                "captureMethod",
                "timestamp",
                "filePath",
                "filePublic",
                "fileName",
                "fileMediatype",
                "exifData",
            ]
        )

        # Get all recordings
        page = 1
        page_size = 100
        while True:
            recordings, total = await self.recording_repo.list_by_dataset(
                dataset_id, page=page, page_size=page_size, sort_by="datetime", sort_order="asc"
            )

            if not recordings:
                break

            for recording in recordings:
                exif_data = json.dumps(
                    {
                        "duration": recording.duration,
                        "samplerate": recording.samplerate,
                        "channels": recording.channels,
                        "bit_depth": recording.bit_depth,
                        "time_expansion": recording.time_expansion,
                        "hash": recording.hash,
                    }
                )

                # Determine mime type
                ext = Path(recording.filename).suffix.lower()
                mime_types = {
                    ".wav": "audio/wav",
                    ".flac": "audio/flac",
                    ".mp3": "audio/mpeg",
                    ".ogg": "audio/ogg",
                }

                writer.writerow(
                    [
                        # Canonical CamtrapDP join keys (approved 2026-06-09):
                        # mediaID == str(recording.id) and deploymentID ==
                        # str(dataset.id), shared with every observation export.
                        media_id(recording.id),
                        deployment_id(dataset_id),
                        (
                            "audiomoth"
                            if "audiomoth" in recording.filename.lower()
                            else "passive_acoustic"
                        ),
                        recording.datetime.isoformat() if recording.datetime else "",
                        recording.path,
                        "true" if dataset.visibility.value == "public" else "false",
                        recording.filename,
                        mime_types.get(ext, "audio/wav"),
                        exif_data,
                    ]
                )

            page += 1
            if page * page_size > total:
                break

        return output.getvalue()

    async def generate_datapackage_json(self, dataset_id: UUID) -> str:
        """Generate datapackage.json metadata.

        Args:
            dataset_id: Dataset UUID

        Returns:
            JSON content as string

        Raises:
            ValueError: If dataset not found
        """
        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if not dataset:
            raise ValueError("Dataset not found")

        recording_count = await self.recording_repo.count_by_dataset(dataset_id)
        total_duration = await self.recording_repo.get_total_duration_by_dataset(dataset_id)

        # Get date range
        recordings_asc, _ = await self.recording_repo.list_by_dataset(
            dataset_id, page=1, page_size=1, sort_by="datetime", sort_order="asc"
        )
        recordings_desc, _ = await self.recording_repo.list_by_dataset(
            dataset_id, page=1, page_size=1, sort_by="datetime", sort_order="desc"
        )

        start_date = (
            recordings_asc[0].datetime.isoformat()
            if recordings_asc and recordings_asc[0].datetime
            else None
        )
        end_date = (
            recordings_desc[0].datetime.isoformat()
            if recordings_desc and recordings_desc[0].datetime
            else None
        )

        # Get coordinates from site
        coordinates: list[float] = []
        if dataset.site and dataset.site.h3_index_member:
            lat, lng = h3_to_center(dataset.site.h3_index_member)
            coordinates = [lng, lat]  # GeoJSON uses [lng, lat]

        datapackage = {
            "profile": "camtrap-dp",
            "name": dataset.name.lower().replace(" ", "-"),
            "id": str(dataset.id),
            "created": dataset.created_at.isoformat(),
            "title": dataset.name,
            "description": dataset.description or "",
            "version": "1.0.0",
            "contributors": [
                {
                    "title": (
                        dataset.created_by.display_name or dataset.created_by.email
                        if dataset.created_by
                        else "Unknown"
                    ),
                    "role": "creator",
                }
            ],
            "licenses": (
                [
                    {
                        "name": dataset.license.short_name if dataset.license else "Unknown",
                        "title": dataset.license.name if dataset.license else "Unknown License",
                    }
                ]
                if dataset.license
                else []
            ),
            "bibliographicCitation": dataset.doi or "",
            "project": {
                "id": str(dataset.project_id),
                "title": dataset.project.name if dataset.project else "",
            },
            "coordinatePrecision": 0.0001,
            "spatial": {
                "type": "Point",
                "coordinates": coordinates,
            },
            "temporal": {
                "start": start_date,
                "end": end_date,
            },
            "taxonomic": [],
            "resources": [
                {
                    "name": "deployments",
                    "path": "deployments.csv",
                    "schema": "deployments-table-schema.json",
                },
                {
                    "name": "media",
                    "path": "media.csv",
                    "schema": "media-table-schema.json",
                },
            ],
            "directory": dataset.audio_dir,
            "stats": {
                "recording_count": recording_count,
                "total_duration_seconds": total_duration,
            },
        }

        return json.dumps(datapackage, indent=2)

    async def export_dataset_zip(
        self,
        dataset_id: UUID,
        include_audio: bool = False,
    ) -> AsyncGenerator[bytes, None]:
        """Generate streaming ZIP file for dataset export.

        Args:
            dataset_id: Dataset UUID
            include_audio: Whether to include audio files

        Yields:
            ZIP file chunks

        Raises:
            ValueError: If dataset not found
        """
        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if not dataset:
            raise ValueError("Dataset not found")

        # Create in-memory ZIP
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add datapackage.json
            datapackage = await self.generate_datapackage_json(dataset_id)
            zf.writestr("datapackage.json", datapackage)

            # Add deployments.csv
            deployments = await self.generate_deployments_csv(dataset_id)
            zf.writestr("deployments.csv", deployments)

            # Add media.csv
            media = await self.generate_media_csv(dataset_id)
            zf.writestr("media.csv", media)

            # Add audio files if requested
            if include_audio and self.audio_service:
                page = 1
                while True:
                    recordings, total = await self.recording_repo.list_by_dataset(
                        dataset_id, page=page, page_size=50
                    )
                    if not recordings:
                        break

                    for recording in recordings:
                        try:
                            file_path = await asyncio.to_thread(
                                self.audio_service.ensure_file_local, recording.path
                            )
                            zf.write(file_path, f"data/{recording.path}")
                        except Exception:
                            pass  # Skip files that can't be read

                    page += 1
                    if page * 50 > total:
                        break

        # Yield ZIP content
        zip_buffer.seek(0)
        while chunk := zip_buffer.read(8192):
            yield chunk
