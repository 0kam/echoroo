"""Seed browser E2E permission fixtures into a local development database.

The script is intentionally narrow: it only upserts users, projects,
memberships, and small content rows with a caller-controlled prefix. It
does not wipe the database and it leaves historical removed memberships
untouched.

Usage::

    uv run python -m echoroo.scripts.seed_e2e_permissions --confirm
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import logging
import math
import secrets
import struct
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import pyotp
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core import s3
from echoroo.core.database import AsyncSessionLocal
from echoroo.core.permissions import Permission
from echoroo.core.redis import get_redis_connection
from echoroo.core.security import hash_password
from echoroo.core.settings import get_settings
from echoroo.models.api_key import ApiKey
from echoroo.models.clip import Clip
from echoroo.models.dataset import Dataset
from echoroo.models.detection import Detection
from echoroo.models.embedding import Embedding
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    DatetimeParseStatus,
    DetectionSource,
    DetectionStatus,
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectMemberRole,
    ProjectStatus,
    ProjectTrustedStatus,
    ProjectVisibility,
    SearchSessionStatus,
)
from echoroo.models.project import Project, ProjectInvitation, ProjectMember
from echoroo.models.project_trusted_user import ProjectTrustedUser
from echoroo.models.recording import Recording
from echoroo.models.recording_annotation import RecordingAnnotation
from echoroo.models.search_session import SearchSession
from echoroo.models.site import Site
from echoroo.models.user import User
from echoroo.services.api_key_verification import hash_api_key_secret
from echoroo.services.invitation_service import (
    coerce_granted_permissions,
    hash_email,
    hash_token,
)
from echoroo.services.two_factor_service import (
    TOTP_SECRET_LENGTH,
    _current_dek_version,
    _encrypt_totp_secret,
)

logger = logging.getLogger("echoroo.scripts.seed_e2e_permissions")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

DEFAULT_PREFIX = "e2e"
DEFAULT_PASSWORD = "E2E-Test-Password-123!"
EMAIL_DOMAIN = "echoroo.app"
MIN_PASSWORD_LENGTH = 16
REGISTERED_TIMEZONE = "Asia/Tokyo"
PROTECTED_ENVIRONMENTS = {"staging", "production"}
LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db", "echoroo-db"})

USER_ROLES = (
    "owner",
    "admin",
    "member",
    "viewer",
    "trusted",
    "trusted_lifecycle",
    "nonmember",
)
MEMBERSHIP_ROLES: dict[str, ProjectMemberRole] = {
    "admin": ProjectMemberRole.ADMIN,
    "member": ProjectMemberRole.MEMBER,
    "viewer": ProjectMemberRole.VIEWER,
}
TRUSTED_PERMISSION_VALUES = (
    Permission.VIEW_MEDIA.value,
    Permission.VIEW_DETECTION.value,
    Permission.VIEW_PRECISE_LOCATION.value,
    Permission.DOWNLOAD.value,
    Permission.EXPORT.value,
    Permission.SEARCH_WITHIN_PROJECT.value,
    Permission.VOTE.value,
    Permission.COMMENT.value,
)
TRUSTED_DURATION_SECONDS = 30 * 24 * 3600
API_KEY_DURATION_SECONDS = 30 * 24 * 3600
PUBLIC_AUTHENTICATED_PERMISSION_VALUES = (
    Permission.VIEW_PROJECT_METADATA.value,
    Permission.VIEW_DATASET_LIST.value,
    Permission.VIEW_MEDIA.value,
    Permission.VIEW_DETECTION.value,
    Permission.SEARCH_WITHIN_PROJECT.value,
    Permission.SEARCH_CROSS_PROJECT.value,
    Permission.DOWNLOAD.value,
    Permission.EXPORT.value,
    Permission.VOTE.value,
    Permission.COMMENT.value,
)


def _permission_value_union(*permission_groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({permission for group in permission_groups for permission in group}))


API_KEY_MEMBER_PERMISSION_VALUES = _permission_value_union(
    PUBLIC_AUTHENTICATED_PERMISSION_VALUES,
    (
        Permission.VIEW_PRECISE_LOCATION.value,
        Permission.MANAGE_DATASET.value,
    ),
)
API_KEY_ADMIN_PERMISSION_VALUES = _permission_value_union(
    API_KEY_MEMBER_PERMISSION_VALUES,
    (
        Permission.MANAGE_DATASET_ADMIN.value,
        Permission.MANAGE_MEMBERS.value,
        Permission.EDIT_PROJECT.value,
    ),
)
API_KEY_OWNER_PERMISSION_VALUES = _permission_value_union(
    API_KEY_ADMIN_PERMISSION_VALUES,
    (
        Permission.MANAGE_TRUSTED.value,
        Permission.DELETE_PROJECT.value,
    ),
)
API_KEY_ROLE_PERMISSION_VALUES: dict[str, tuple[str, ...]] = {
    "owner": API_KEY_OWNER_PERMISSION_VALUES,
    "admin": API_KEY_ADMIN_PERMISSION_VALUES,
    "member": API_KEY_MEMBER_PERMISSION_VALUES,
    "viewer": PUBLIC_AUTHENTICATED_PERMISSION_VALUES,
    "trusted": _permission_value_union(
        PUBLIC_AUTHENTICATED_PERMISSION_VALUES,
        TRUSTED_PERMISSION_VALUES,
    ),
    "trusted_lifecycle": _permission_value_union(
        PUBLIC_AUTHENTICATED_PERMISSION_VALUES,
        TRUSTED_PERMISSION_VALUES,
    ),
    "nonmember": PUBLIC_AUTHENTICATED_PERMISSION_VALUES,
}
API_KEY_ENV_NAMES: dict[str, str] = {
    "owner": "E2E_OWNER_API_KEY",
    "admin": "E2E_ADMIN_API_KEY",
    "member": "E2E_MEMBER_API_KEY",
    "viewer": "E2E_VIEWER_API_KEY",
    "trusted": "E2E_TRUSTED_API_KEY",
    "trusted_lifecycle": "E2E_TRUSTED_LIFECYCLE_API_KEY",
    "nonmember": "E2E_NONMEMBER_API_KEY",
}
TWO_FACTOR_FAILURE_KEY_TEMPLATES = (
    "2fa:totp_fail:{user_id}",
    "2fa:totp_consecutive_fail:{user_id}",
    "2fa:totp_lock:{user_id}",
    "2fa:backup_fail:{user_id}",
)

RESTRICTED_CONFIG: dict[str, Any] = {
    "allow_media_playback": True,
    "allow_detection_view": True,
    "mask_species_in_detection": False,
    "allow_download": False,
    "allow_export": False,
    "allow_voting_and_comments": True,
    "public_location_precision_h3_res": 5,
    "allow_precise_location_to_viewer": False,
}

FIXTURE_DURATION_SECONDS = 12.5
FIXTURE_SAMPLE_RATE = 48_000
FIXTURE_CHANNELS = 2
FIXTURE_BIT_DEPTH = 16
FIXTURE_TONE_HZ = 880.0
FIXTURE_AMPLITUDE = 0.15
EXPORTABLE_SPECIES_KEY = "00000000-0000-4000-8000-000000000007"
SEEDED_MODEL_NAME = "e2e-seeded-model"


@dataclass(frozen=True)
class ContentFixture:
    """Small project content seeded for browser smoke flows."""

    site: Site
    dataset: Dataset
    recording: Recording
    embedding: Embedding
    clip: Clip
    detection: Detection
    annotation: RecordingAnnotation


def _build_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser."""
    parser = argparse.ArgumentParser(
        prog="echoroo.scripts.seed_e2e_permissions",
        description=(
            "Idempotently seed local browser E2E permission fixtures. "
            "Only rows using the chosen prefix are created or updated."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Required acknowledgement that this script mutates the local "
            "development database. Without --confirm it exits non-zero."
        ),
    )
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help=f"Prefix for fixture emails and project names (default: {DEFAULT_PREFIX!r}).",
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help=(
            "Password assigned to all seeded users. Must be at least "
            f"{MIN_PASSWORD_LENGTH} characters."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Accepted for compatibility; stdout is always JSON.",
    )
    parser.add_argument(
        "--allow-non-local-database",
        action="store_true",
        help=(
            "Allow DATABASE_URL hosts outside the local/dev allowlist. This is intended "
            "for CI or development containers and never overrides staging/production "
            "ENVIRONMENT protection."
        ),
    )
    return parser


def _database_host(database_url: str) -> str | None:
    """Return the hostname from a PostgreSQL URL."""
    return urlparse(database_url).hostname


def _validate_environment_safety(*, allow_non_local_database: bool) -> None:
    """Refuse protected environments and non-local DB hosts before DB mutation."""
    settings = get_settings()
    environment = settings.ENVIRONMENT.lower()
    if environment in PROTECTED_ENVIRONMENTS:
        raise SystemExit(
            "Refusing to run in ENVIRONMENT="
            f"{settings.ENVIRONMENT!r}; this fixture seeder is for local development only."
        )

    database_host = _database_host(settings.DATABASE_URL)
    if allow_non_local_database:
        return

    if database_host is None or database_host.lower() not in LOCAL_DATABASE_HOSTS:
        host_label = database_host if database_host is not None else "<missing>"
        allowed = ", ".join(sorted(LOCAL_DATABASE_HOSTS))
        raise SystemExit(
            "Refusing to run against non-local DATABASE_URL host "
            f"{host_label!r}. Allowed hosts: {allowed}. Use "
            "--allow-non-local-database only for CI or development containers."
        )


def _security_stamp() -> str:
    """Return a fresh 64-character stamp compatible with users.security_stamp."""
    return secrets.token_hex(32)


def _user_email(prefix: str, role: str) -> str:
    return f"{prefix}-{role}@{EMAIL_DOMAIN}"


def _display_name(prefix: str, role: str) -> str:
    return f"{prefix.upper()} {role.title()} E2E User"


def _api_key_prefix(prefix: str, role: str) -> str:
    digest = hashlib.sha256(f"e2e:{prefix}:{role}:api-key-prefix".encode()).hexdigest()
    return f"echoroo_{digest[:8]}"


def _fixture_wav_bytes() -> bytes:
    """Build a deterministic small WAV matching seeded recording metadata."""
    frame_count = int(FIXTURE_DURATION_SECONDS * FIXTURE_SAMPLE_RATE)
    max_amplitude = int((2 ** (FIXTURE_BIT_DEPTH - 1) - 1) * FIXTURE_AMPLITUDE)
    frames = bytearray(frame_count * FIXTURE_CHANNELS * (FIXTURE_BIT_DEPTH // 8))

    offset = 0
    for index in range(frame_count):
        sample = int(
            max_amplitude * math.sin(2 * math.pi * FIXTURE_TONE_HZ * index / FIXTURE_SAMPLE_RATE)
        )
        packed = struct.pack("<h", sample)
        for _channel in range(FIXTURE_CHANNELS):
            frames[offset : offset + 2] = packed
            offset += 2

    with io.BytesIO() as buffer:
        import wave

        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(FIXTURE_CHANNELS)
            wav.setsampwidth(FIXTURE_BIT_DEPTH // 8)
            wav.setframerate(FIXTURE_SAMPLE_RATE)
            wav.writeframes(frames)
        return buffer.getvalue()


def _fixture_wav_sha256() -> str:
    """Return the deterministic fixture WAV SHA-256 digest."""
    return hashlib.sha256(_fixture_wav_bytes()).hexdigest()


def _write_local_media_fixture(path: str, payload: bytes) -> None:
    """Write the fixture under AUDIO_ROOT so AudioService can find it locally."""
    settings = get_settings()
    destination = Path(settings.AUDIO_ROOT) / path
    resolved_root = Path(settings.AUDIO_ROOT).resolve()
    resolved_destination = destination.resolve()
    if not resolved_destination.is_relative_to(resolved_root):
        raise ValueError(f"Path traversal detected for fixture media path: {path}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() == payload:
        return
    destination.write_bytes(payload)


def _ensure_recording_media_fixture(path: str) -> str:
    """Ensure the seeded recording path resolves through AudioService.

    Prefer S3 so ``AudioService.ensure_file_local()`` exercises its production
    lookup path. Write below ``AUDIO_ROOT`` only as a fallback when S3 seeding
    is unavailable.
    """
    payload = _fixture_wav_bytes()
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    settings = get_settings()

    try:
        client = s3.get_s3_client()
        s3.ensure_bucket_exists(client)
        existing = s3.verify_object_exists(
            path,
            expected_size=len(payload),
            expected_sha256=expected_sha256,
            client=client,
        )
        if existing["exists"] and existing["size_match"] and existing["sha256_match"]:
            return "s3"

        client.put_object(
            Bucket=settings.S3_BUCKET,
            Key=path,
            Body=payload,
            ContentType="audio/wav",
            Metadata={
                "source": "seed_e2e_permissions",
                "sha256": expected_sha256,
            },
        )
        return "s3"
    except Exception as exc:  # noqa: BLE001 - seeding supports local fallback.
        logger.warning(
            "Unable to seed media fixture %s to S3; using AUDIO_ROOT fixture: %s",
            path,
            exc,
        )
        _write_local_media_fixture(path, payload)
        return "local"


def _ensure_reference_audio_fixture(path: str) -> None:
    """Ensure an exportable search session reference audio object exists in S3."""
    payload = _fixture_wav_bytes()
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    settings = get_settings()
    client = s3.get_s3_client()
    s3.ensure_bucket_exists(client)

    existing = s3.verify_object_exists(
        path,
        expected_size=len(payload),
        expected_sha256=expected_sha256,
        client=client,
    )
    if existing["exists"] and existing["size_match"] and existing["sha256_match"]:
        return

    client.put_object(
        Bucket=settings.S3_BUCKET,
        Key=path,
        Body=payload,
        ContentType="audio/wav",
        Metadata={
            "source": "seed_e2e_permissions",
            "sha256": expected_sha256,
        },
    )


async def _upsert_user(
    session: AsyncSession,
    *,
    prefix: str,
    role: str,
    password: str,
) -> tuple[User, str]:
    """Create or update one fixture user and replace its TOTP secret."""
    email = _user_email(prefix, role)
    result = await session.execute(sa.select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            id=uuid4(),
            email=email,
            password_hash=hash_password(password),
            display_name=_display_name(prefix, role),
            security_stamp=_security_stamp(),
            two_factor_enabled=True,
            two_factor_backup_codes_hashed=[],
            registered_timezone=REGISTERED_TIMEZONE,
        )
        session.add(user)
    else:
        user.password_hash = hash_password(password)
        user.display_name = _display_name(prefix, role)
        user.security_stamp = _security_stamp()
        user.two_factor_enabled = True
        user.registered_timezone = REGISTERED_TIMEZONE
        user.deleted_at = None
        user.two_factor_reset_cooldown_until = None

    totp_secret = pyotp.random_base32(length=TOTP_SECRET_LENGTH)
    user.two_factor_secret_encrypted = _encrypt_totp_secret(totp_secret)
    user.two_factor_secret_dek_version = _current_dek_version()

    await session.flush()
    return user, totp_secret


async def _clear_two_factor_failure_state(user: User) -> None:
    """Best-effort cleanup for Redis-backed 2FA failure and lockout counters."""
    keys = [template.format(user_id=user.id) for template in TWO_FACTOR_FAILURE_KEY_TEMPLATES]
    try:
        redis = await get_redis_connection()
        await redis.delete(*keys)
    except Exception as exc:  # noqa: BLE001 - fixture seeding must not depend on Redis.
        logger.warning(
            "Unable to clear Redis 2FA failure state for fixture user %s: %s",
            user.id,
            exc,
        )


async def _upsert_api_key(
    session: AsyncSession,
    *,
    prefix: str,
    role: str,
    user: User,
) -> tuple[ApiKey, str]:
    """Create or update one API key fixture for a role."""
    key_prefix = _api_key_prefix(prefix, role)
    raw_secret = secrets.token_urlsafe(32)
    raw_key = f"{key_prefix}_{raw_secret}"
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=API_KEY_DURATION_SECONDS)
    granted_permissions = list(API_KEY_ROLE_PERMISSION_VALUES[role])

    result = await session.execute(sa.select(ApiKey).where(ApiKey.prefix == key_prefix))
    api_key = result.scalar_one_or_none()

    if api_key is None:
        api_key = ApiKey(
            id=uuid4(),
            user_id=user.id,
            prefix=key_prefix,
            hashed_secret=hash_api_key_secret(raw_secret),
            granted_permissions=granted_permissions,
            project_id=None,
            allowed_ip_cidrs=None,
            expires_at=expires_at,
            revoked_at=None,
            revoked_reason=None,
            last_used_at=None,
            scope_violation_count_10min=0,
            ip_violation_count=0,
        )
        session.add(api_key)
    else:
        api_key.user_id = user.id
        api_key.hashed_secret = hash_api_key_secret(raw_secret)
        api_key.granted_permissions = granted_permissions
        api_key.project_id = None
        api_key.allowed_ip_cidrs = None
        api_key.expires_at = expires_at
        api_key.revoked_at = None
        api_key.revoked_reason = None
        api_key.last_used_at = None

    await session.flush()
    return api_key, raw_key


async def _upsert_project(
    session: AsyncSession,
    *,
    prefix: str,
    owner: User,
    kind: str,
    visibility: ProjectVisibility,
    restricted_config: dict[str, Any],
) -> Project:
    """Create or update one fixture project by deterministic name."""
    name = f"{prefix} E2E {kind.title()} Permission Project"
    result = await session.execute(
        sa.select(Project)
        .where(Project.name == name, Project.owner_id == owner.id)
        .order_by(Project.created_at.asc())
        .limit(1)
    )
    project = result.scalar_one_or_none()

    if project is None:
        project = Project(
            id=uuid4(),
            name=name,
            description=f"{kind.title()} browser E2E permission fixture.",
            owner_id=owner.id,
            visibility=visibility,
            license_id="cc-by",
            status=ProjectStatus.ACTIVE,
            restricted_config=dict(restricted_config),
            restricted_config_version=1,
        )
        session.add(project)
    else:
        project.description = f"{kind.title()} browser E2E permission fixture."
        project.owner_id = owner.id
        project.visibility = visibility
        project.license_id = "cc-by"
        project.status = ProjectStatus.ACTIVE
        project.dormant_since = None
        project.archived_since = None
        project.restricted_config = dict(restricted_config)

    await session.flush()
    return project


async def _upsert_membership(
    session: AsyncSession,
    *,
    project: Project,
    user: User,
    role: ProjectMemberRole,
    invited_by: User,
) -> ProjectMember:
    """Create or update the active membership row for a user/project pair."""
    result = await session.execute(
        sa.select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user.id,
            ProjectMember.removed_at.is_(None),
        )
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        membership = ProjectMember(
            id=uuid4(),
            project_id=project.id,
            user_id=user.id,
            role=role,
            invited_by_id=invited_by.id,
        )
        session.add(membership)
    else:
        membership.role = role
        membership.invited_by_id = invited_by.id
        membership.expires_at = None

    await session.flush()
    return membership


async def _upsert_site(
    session: AsyncSession,
    *,
    project: Project,
    name: str,
) -> Site:
    result = await session.execute(
        sa.select(Site).where(Site.project_id == project.id, Site.name == name)
    )
    site = result.scalar_one_or_none()
    if site is None:
        site = Site(
            id=uuid4(),
            project_id=project.id,
            name=name,
            h3_index_member="8928308280fffff",
            h3_index_member_resolution=9,
        )
        session.add(site)
    else:
        site.h3_index_member = "8928308280fffff"
        site.h3_index_member_resolution = 9

    await session.flush()
    return site


async def _upsert_dataset(
    session: AsyncSession,
    *,
    project: Project,
    site: Site,
    owner: User,
    name: str,
) -> Dataset:
    result = await session.execute(
        sa.select(Dataset).where(Dataset.project_id == project.id, Dataset.name == name)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        dataset = Dataset(
            id=uuid4(),
            project_id=project.id,
            site_id=site.id,
            created_by_id=owner.id,
            name=name,
            description="Browser E2E fixture dataset.",
            visibility=DatasetVisibility.PUBLIC,
            status=DatasetStatus.COMPLETED,
            total_files=1,
            processed_files=1,
        )
        session.add(dataset)
    else:
        dataset.site_id = site.id
        dataset.created_by_id = owner.id
        dataset.description = "Browser E2E fixture dataset."
        dataset.visibility = DatasetVisibility.PUBLIC
        dataset.status = DatasetStatus.COMPLETED
        dataset.total_files = 1
        dataset.processed_files = 1
        dataset.processing_error = None

    await session.flush()
    return dataset


async def _upsert_recording(
    session: AsyncSession,
    *,
    dataset: Dataset,
    site: Site,
    prefix: str,
    kind: str,
) -> Recording:
    path = f"e2e/{prefix}/{kind}/fixture.wav"
    _ensure_recording_media_fixture(path)
    media_hash = _fixture_wav_sha256()
    result = await session.execute(
        sa.select(Recording).where(
            Recording.dataset_id == dataset.id,
            Recording.path == path,
        )
    )
    recording = result.scalar_one_or_none()
    if recording is None:
        recording = Recording(
            id=uuid4(),
            dataset_id=dataset.id,
            site_id=site.id,
            filename=f"{prefix}-{kind}-fixture.wav",
            path=path,
            hash=media_hash,
            duration=FIXTURE_DURATION_SECONDS,
            samplerate=FIXTURE_SAMPLE_RATE,
            channels=FIXTURE_CHANNELS,
            bit_depth=FIXTURE_BIT_DEPTH,
            datetime=datetime(2026, 5, 15, 9, 0, tzinfo=UTC),
            datetime_parse_status=DatetimeParseStatus.SUCCESS,
            time_expansion=1.0,
            h3_index_member=site.h3_index_member,
            h3_index_member_resolution=9,
            gps_stripped=True,
        )
        session.add(recording)
    else:
        recording.site_id = site.id
        recording.filename = f"{prefix}-{kind}-fixture.wav"
        recording.hash = media_hash
        recording.duration = FIXTURE_DURATION_SECONDS
        recording.samplerate = FIXTURE_SAMPLE_RATE
        recording.channels = FIXTURE_CHANNELS
        recording.bit_depth = FIXTURE_BIT_DEPTH
        recording.datetime = datetime(2026, 5, 15, 9, 0, tzinfo=UTC)
        recording.datetime_parse_status = DatetimeParseStatus.SUCCESS
        recording.datetime_parse_error = None
        recording.time_expansion = 1.0
        recording.h3_index_member = site.h3_index_member
        recording.h3_index_member_resolution = 9
        recording.gps_stripped = True

    await session.flush()
    return recording


async def _upsert_detection(
    session: AsyncSession,
    *,
    project: Project,
    recording: Recording,
) -> Detection:
    result = await session.execute(
        sa.select(Detection)
        .where(
            Detection.project_id == project.id,
            Detection.recording_id == recording.id,
            Detection.source == DetectionSource.BIRDNET,
            Detection.start_time == 1.0,
            Detection.end_time == 2.5,
        )
        .order_by(Detection.created_at.asc())
        .limit(1)
    )
    detection = result.scalar_one_or_none()
    if detection is None:
        detection = Detection(
            id=uuid4(),
            project_id=project.id,
            recording_id=recording.id,
            taxon_id="9192711",
            source=DetectionSource.BIRDNET,
            status=DetectionStatus.UNREVIEWED,
            start_time=1.0,
            end_time=2.5,
            confidence=0.87,
        )
        session.add(detection)
    else:
        detection.taxon_id = "9192711"
        detection.status = DetectionStatus.UNREVIEWED
        detection.confidence = 0.87

    await session.flush()
    return detection


async def _upsert_embedding(
    session: AsyncSession,
    *,
    recording: Recording,
) -> Embedding:
    result = await session.execute(
        sa.select(Embedding)
        .where(
            Embedding.recording_id == recording.id,
            Embedding.model_name == SEEDED_MODEL_NAME,
            Embedding.start_time == 1.0,
            Embedding.end_time == 2.5,
        )
        .order_by(Embedding.created_at.asc())
        .limit(1)
    )
    embedding = result.scalar_one_or_none()
    vector = [1.0] + [0.0] * 1535
    if embedding is None:
        embedding = Embedding(
            id=uuid4(),
            recording_id=recording.id,
            detection_run_id=None,
            model_name=SEEDED_MODEL_NAME,
            model_version=None,
            start_time=1.0,
            end_time=2.5,
            vector=vector,
        )
        session.add(embedding)
    else:
        embedding.detection_run_id = None
        embedding.model_version = None
        embedding.vector = vector

    await session.flush()
    return embedding


async def _upsert_clip(
    session: AsyncSession,
    *,
    recording: Recording,
) -> Clip:
    """Seed one stable clip inside the deterministic 12.5 second WAV."""
    result = await session.execute(
        sa.select(Clip)
        .where(
            Clip.recording_id == recording.id,
            Clip.start_time == 1.0,
            Clip.end_time == 2.5,
        )
        .order_by(Clip.created_at.asc())
        .limit(1)
    )
    clip = result.scalar_one_or_none()
    if clip is None:
        clip = Clip(
            id=uuid4(),
            recording_id=recording.id,
            start_time=1.0,
            end_time=2.5,
            note="E2E fixture clip covering the deterministic tone.",
        )
        session.add(clip)
    else:
        clip.note = "E2E fixture clip covering the deterministic tone."

    await session.flush()
    return clip


async def _upsert_recording_annotation(
    session: AsyncSession,
    *,
    recording: Recording,
    detection: Detection,
) -> RecordingAnnotation:
    """Seed one canonical ``recording_annotations`` row for the recording.

    Post-P2 the vote / comment endpoints validate ``annotation_id`` against the
    ``recording_annotations`` table via the ``recording -> dataset -> project``
    scope chain (``AnnotationRepository.exists_in_project``). The seeded row
    therefore MUST hang off the seeded project's recording so that the vote
    flows exercised by the browser E2E specs
    (``permissions/seeded-vote-comment.spec.ts`` and ``phase6-vote-flow.spec.ts``
    via ``E2E_PUBLIC_ANNOTATION_ID`` / ``E2E_RESTRICTED_ANNOTATION_ID``) resolve.

    Field choices:
      * ``recording_id`` — the seeded recording, anchoring the BOLA scope chain.
      * ``source`` — ``BIRDNET`` to mirror the seeded detection's model source.
      * ``status`` — ``UNREVIEWED`` so the annotation is open for voting
        (the per-source consensus widget starts in the needs-votes state).
      * ``start_time`` / ``end_time`` — copied from the seeded detection so the
        annotation aligns with the deterministic fixture clip.
      * ``tag_id`` — ``None``: the seed never materialises ``tags`` ORM rows, and
        the vote endpoints do not require a tag (only the project scope chain).

    Idempotent: re-running locates the existing row by
    (``recording_id``, ``source``, ``start_time``, ``end_time``) and refreshes
    its mutable fields, following the other ``_upsert_*`` helpers in this file.
    """
    result = await session.execute(
        sa.select(RecordingAnnotation)
        .where(
            RecordingAnnotation.recording_id == recording.id,
            RecordingAnnotation.source == DetectionSource.BIRDNET,
            RecordingAnnotation.start_time == detection.start_time,
            RecordingAnnotation.end_time == detection.end_time,
        )
        .order_by(RecordingAnnotation.created_at.asc())
        .limit(1)
    )
    annotation = result.scalar_one_or_none()
    if annotation is None:
        annotation = RecordingAnnotation(
            id=uuid4(),
            recording_id=recording.id,
            tag_id=None,
            source=DetectionSource.BIRDNET,
            status=DetectionStatus.UNREVIEWED,
            confidence=detection.confidence,
            start_time=detection.start_time,
            end_time=detection.end_time,
        )
        session.add(annotation)
    else:
        annotation.tag_id = None
        annotation.status = DetectionStatus.UNREVIEWED
        annotation.confidence = detection.confidence

    await session.flush()
    return annotation


async def _upsert_trusted_overlay(
    session: AsyncSession,
    *,
    project: Project,
    trusted_user: User,
    granted_by: User,
    email_hash_secret: str,
    token_suffix: str = "trusted",
    status: ProjectTrustedStatus = ProjectTrustedStatus.ACTIVE,
    granted_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> ProjectTrustedUser:
    now = datetime.now(UTC)
    granted_at = granted_at or now
    expires_at = expires_at or (granted_at + timedelta(seconds=TRUSTED_DURATION_SECONDS))
    email_hash = hash_email(trusted_user.email, hmac_secret=email_hash_secret)
    granted_permissions = sorted(
        permission.value for permission in coerce_granted_permissions(TRUSTED_PERMISSION_VALUES)
    )
    token_hash = hash_token(f"e2e:{project.id}:{trusted_user.id}:{token_suffix}")

    invitation_result = await session.execute(
        sa.select(ProjectInvitation)
        .where(
            ProjectInvitation.project_id == project.id,
            ProjectInvitation.kind == ProjectInvitationKind.TRUSTED,
            ProjectInvitation.token_hash == token_hash,
        )
        .order_by(ProjectInvitation.created_at.asc())
        .limit(1)
    )
    invitation = invitation_result.scalar_one_or_none()
    if invitation is None:
        invitation = ProjectInvitation(
            id=uuid4(),
            project_id=project.id,
            kind=ProjectInvitationKind.TRUSTED,
            email=trusted_user.email,
            email_hash=email_hash,
            email_hash_v2=None,
            pii_hash_version=None,
            role=None,
            granted_permissions=granted_permissions,
            trusted_duration_seconds=TRUSTED_DURATION_SECONDS,
            token_hash=token_hash,
            invited_by_id=granted_by.id,
            expires_at=expires_at,
            accepted_at=granted_at,
            status=ProjectInvitationStatus.ACCEPTED,
        )
        session.add(invitation)
    else:
        invitation.email = trusted_user.email
        invitation.email_hash = email_hash
        invitation.email_hash_v2 = None
        invitation.pii_hash_version = None
        invitation.role = None
        invitation.granted_permissions = granted_permissions
        invitation.trusted_duration_seconds = TRUSTED_DURATION_SECONDS
        invitation.token_hash = token_hash
        invitation.invited_by_id = granted_by.id
        invitation.expires_at = expires_at
        invitation.accepted_at = granted_at
        invitation.declined_at = None
        invitation.revoked_at = None
        invitation.status = ProjectInvitationStatus.ACCEPTED

    await session.flush()

    overlay_lookup = sa.select(ProjectTrustedUser).where(
        ProjectTrustedUser.project_id == project.id,
        ProjectTrustedUser.user_id == trusted_user.id,
    )
    if status == ProjectTrustedStatus.ACTIVE:
        overlay_lookup = overlay_lookup.where(
            ProjectTrustedUser.status == ProjectTrustedStatus.ACTIVE
        )
    else:
        overlay_lookup = overlay_lookup.where(ProjectTrustedUser.invitation_id == invitation.id)
    overlay_result = await session.execute(
        overlay_lookup.order_by(ProjectTrustedUser.created_at.asc()).limit(1)
    )
    overlay = overlay_result.scalar_one_or_none()
    if overlay is None:
        overlay = ProjectTrustedUser(
            id=uuid4(),
            project_id=project.id,
            user_id=trusted_user.id,
            invitation_id=invitation.id,
            granted_by_id=granted_by.id,
            granted_at=granted_at,
            expires_at=expires_at,
            status=status,
            granted_permissions=granted_permissions,
            email_at_invitation=trusted_user.email,
            email_at_invitation_hash=email_hash,
        )
        session.add(overlay)
    else:
        overlay.invitation_id = invitation.id
        overlay.granted_by_id = granted_by.id
        overlay.granted_at = granted_at
        overlay.expires_at = expires_at
        overlay.granted_permissions = granted_permissions
        overlay.email_at_invitation = trusted_user.email
        overlay.email_at_invitation_hash = email_hash
        overlay.revoked_at = None
        overlay.status = status

    await session.flush()
    return overlay


async def _upsert_content(
    session: AsyncSession,
    *,
    prefix: str,
    owner: User,
    project: Project,
    kind: str,
) -> ContentFixture:
    """Seed one Site, Dataset, Recording, and Detection for a project."""
    site = await _upsert_site(
        session,
        project=project,
        name=f"{prefix} E2E {kind.title()} Site",
    )
    dataset = await _upsert_dataset(
        session,
        project=project,
        site=site,
        owner=owner,
        name=f"{prefix} E2E {kind.title()} Dataset",
    )
    recording = await _upsert_recording(
        session,
        dataset=dataset,
        site=site,
        prefix=prefix,
        kind=kind,
    )
    detection = await _upsert_detection(
        session,
        project=project,
        recording=recording,
    )
    embedding = await _upsert_embedding(session, recording=recording)
    clip = await _upsert_clip(session, recording=recording)
    annotation = await _upsert_recording_annotation(
        session, recording=recording, detection=detection
    )
    return ContentFixture(
        site=site,
        dataset=dataset,
        recording=recording,
        embedding=embedding,
        clip=clip,
        detection=detection,
        annotation=annotation,
    )


async def _upsert_search_session(
    session: AsyncSession,
    *,
    prefix: str,
    owner: User,
    project: Project,
    content: ContentFixture,
    kind: str,
) -> SearchSession:
    """Seed one completed, storage-free SearchSession for a project."""
    name = f"{prefix} E2E {kind.title()} Search Session"
    result = await session.execute(
        sa.select(SearchSession)
        .where(
            SearchSession.project_id == project.id,
            SearchSession.name == name,
        )
        .order_by(SearchSession.created_at.asc())
        .limit(1)
    )
    search_session = result.scalar_one_or_none()
    started_at = datetime(2026, 5, 15, 9, 5, tzinfo=UTC)
    completed_at = datetime(2026, 5, 15, 9, 6, tzinfo=UTC)
    parameters: dict[str, object] = {
        "dataset_id": str(content.dataset.id),
        "limit_per_species": 10,
        "min_similarity": 0.8,
    }
    species_config: list[object] = [
        {
            "common_name": "E2E Seed Species",
            "scientific_name": "Testus permissionis",
            "tag_id": "9192711",
        }
    ]

    if search_session is None:
        search_session = SearchSession(
            id=uuid4(),
            project_id=project.id,
            user_id=owner.id,
            name=name,
            status=SearchSessionStatus.COMPLETED,
            model_name=SEEDED_MODEL_NAME,
            parameters=parameters,
            species_config=species_config,
            results=None,
            result_count=0,
            confirmed_count=0,
            rejected_count=0,
            celery_job_id=None,
            reference_audio_keys=None,
            started_at=started_at,
            completed_at=completed_at,
            error_message=None,
        )
        session.add(search_session)
    else:
        search_session.user_id = owner.id
        search_session.status = SearchSessionStatus.COMPLETED
        search_session.model_name = SEEDED_MODEL_NAME
        search_session.parameters = parameters
        search_session.species_config = species_config
        search_session.results = None
        search_session.result_count = 0
        search_session.confirmed_count = 0
        search_session.rejected_count = 0
        search_session.celery_job_id = None
        search_session.reference_audio_keys = None
        search_session.started_at = started_at
        search_session.completed_at = completed_at
        search_session.error_message = None

    await session.flush()
    return search_session


async def _upsert_exportable_search_session(
    session: AsyncSession,
    *,
    prefix: str,
    owner: User,
    project: Project,
    content: ContentFixture,
    kind: str,
) -> SearchSession:
    """Seed one completed SearchSession with deterministic exportable results."""
    name = f"{prefix} E2E {kind.title()} Exportable Search Session"
    reference_audio_key = f"e2e/{prefix}/{kind}/reference-audio-0.wav"
    _ensure_reference_audio_fixture(reference_audio_key)
    result = await session.execute(
        sa.select(SearchSession)
        .where(
            SearchSession.project_id == project.id,
            SearchSession.name == name,
        )
        .order_by(SearchSession.created_at.asc())
        .limit(1)
    )
    search_session = result.scalar_one_or_none()
    started_at = datetime(2026, 5, 15, 9, 7, tzinfo=UTC)
    completed_at = datetime(2026, 5, 15, 9, 8, tzinfo=UTC)
    parameters: dict[str, object] = {
        "dataset_id": str(content.dataset.id),
        "limit_per_species": 10,
        "min_similarity": 0.8,
    }
    species_config: list[object] = [
        {
            "tag_id": EXPORTABLE_SPECIES_KEY,
            "scientific_name": "Testus permissionis",
            "common_name": "E2E Seed Species",
            "sources": [],
        }
    ]
    results: dict[str, object] = {
        "results": {
            EXPORTABLE_SPECIES_KEY: {
                "tag_id": EXPORTABLE_SPECIES_KEY,
                "scientific_name": "Testus permissionis",
                "common_name": "E2E Seed Species",
                "matches": [
                    {
                        "embedding_id": str(content.embedding.id),
                        "recording_id": str(content.recording.id),
                        "recording_filename": content.recording.filename,
                        "recording_datetime": content.recording.datetime.isoformat()
                        if content.recording.datetime is not None
                        else None,
                        "dataset_id": str(content.dataset.id),
                        "start_time": 1.0,
                        "end_time": 2.5,
                        "similarity": 1.0,
                    }
                ],
            }
        },
        "total_matches": 1,
        "search_duration_ms": 123,
    }

    if search_session is None:
        search_session = SearchSession(
            id=uuid4(),
            project_id=project.id,
            user_id=owner.id,
            name=name,
            status=SearchSessionStatus.COMPLETED,
            model_name=SEEDED_MODEL_NAME,
            parameters=parameters,
            species_config=species_config,
            results=results,
            result_count=1,
            confirmed_count=0,
            rejected_count=0,
            celery_job_id=None,
            reference_audio_keys=[reference_audio_key],
            started_at=started_at,
            completed_at=completed_at,
            error_message=None,
        )
        session.add(search_session)
    else:
        search_session.user_id = owner.id
        search_session.status = SearchSessionStatus.COMPLETED
        search_session.model_name = SEEDED_MODEL_NAME
        search_session.parameters = parameters
        search_session.species_config = species_config
        search_session.results = results
        search_session.result_count = 1
        search_session.confirmed_count = 0
        search_session.rejected_count = 0
        search_session.celery_job_id = None
        search_session.reference_audio_keys = [reference_audio_key]
        search_session.started_at = started_at
        search_session.completed_at = completed_at
        search_session.error_message = None

    await session.flush()
    return search_session


def _user_payload(user: User, *, role: str) -> dict[str, str]:
    return {
        "role": role,
        "id": str(user.id),
        "email": user.email,
        "totp_secret_env": f"E2E_{role.upper()}_TOTP_SECRET",
    }


def _project_payload(project: Project, content: ContentFixture) -> dict[str, Any]:
    return {
        "id": str(project.id),
        "name": project.name,
        "visibility": project.visibility.value,
        "owner_id": str(project.owner_id),
        "license": project.license,
        "status": project.status.value,
        "site_id": str(content.site.id),
        "dataset_id": str(content.dataset.id),
        "recording_id": str(content.recording.id),
        "embedding_id": str(content.embedding.id),
        "clip_id": str(content.clip.id),
        "detection_id": str(content.detection.id),
        "annotation_id": str(content.annotation.id),
    }


def _search_session_payload(search_session: SearchSession) -> dict[str, Any]:
    return {
        "id": str(search_session.id),
        "project_id": str(search_session.project_id),
        "user_id": None if search_session.user_id is None else str(search_session.user_id),
        "name": search_session.name,
        "status": search_session.status.value,
        "model_name": search_session.model_name,
        "result_count": search_session.result_count,
        "confirmed_count": search_session.confirmed_count,
        "rejected_count": search_session.rejected_count,
        "celery_job_id": search_session.celery_job_id,
        "reference_audio_keys": search_session.reference_audio_keys,
    }


def _api_key_payload(api_key: ApiKey, *, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "id": str(api_key.id),
        "prefix": api_key.prefix,
        "user_id": str(api_key.user_id),
        "project_id": None if api_key.project_id is None else str(api_key.project_id),
        "expires_at": api_key.expires_at.isoformat(),
        "revoked_at": None,
        "allowed_ip_cidrs": api_key.allowed_ip_cidrs,
        "granted_permissions": list(api_key.granted_permissions),
        "raw_key_env": API_KEY_ENV_NAMES[role],
    }


def _env_payload(
    *,
    prefix: str,
    password: str,
    users: dict[str, User],
    totp_secrets: dict[str, str],
    projects: dict[str, Project],
    content: dict[str, ContentFixture],
    search_sessions: dict[str, SearchSession],
    trusted_overlays: dict[str, ProjectTrustedUser],
    raw_api_keys: dict[str, str],
) -> dict[str, str]:
    env = {
        "E2E_FIXTURE_PREFIX": prefix,
        "E2E_PASSWORD": password,
        "E2E_OWNER_EMAIL": users["owner"].email,
        "E2E_OWNER_USER_ID": str(users["owner"].id),
        "E2E_OWNER_TOTP_SECRET": totp_secrets["owner"],
        "E2E_ADMIN_EMAIL": users["admin"].email,
        "E2E_ADMIN_USER_ID": str(users["admin"].id),
        "E2E_ADMIN_TOTP_SECRET": totp_secrets["admin"],
        "E2E_MEMBER_EMAIL": users["member"].email,
        "E2E_MEMBER_USER_ID": str(users["member"].id),
        "E2E_MEMBER_TOTP_SECRET": totp_secrets["member"],
        "E2E_VIEWER_EMAIL": users["viewer"].email,
        "E2E_VIEWER_USER_ID": str(users["viewer"].id),
        "E2E_VIEWER_TOTP_SECRET": totp_secrets["viewer"],
        "E2E_TRUSTED_EMAIL": users["trusted"].email,
        "E2E_TRUSTED_USER_ID": str(users["trusted"].id),
        "E2E_TRUSTED_TOTP_SECRET": totp_secrets["trusted"],
        "E2E_TRUSTED_LIFECYCLE_EMAIL": users["trusted_lifecycle"].email,
        "E2E_TRUSTED_LIFECYCLE_USER_ID": str(users["trusted_lifecycle"].id),
        "E2E_TRUSTED_LIFECYCLE_TOTP_SECRET": totp_secrets["trusted_lifecycle"],
        "E2E_NONMEMBER_EMAIL": users["nonmember"].email,
        "E2E_NONMEMBER_USER_ID": str(users["nonmember"].id),
        "E2E_NONMEMBER_TOTP_SECRET": totp_secrets["nonmember"],
        "E2E_PUBLIC_PROJECT_ID": str(projects["public"].id),
        "E2E_PUBLIC_PROJECT_NAME": projects["public"].name,
        "E2E_PUBLIC_SITE_ID": str(content["public"].site.id),
        "E2E_PUBLIC_DATASET_ID": str(content["public"].dataset.id),
        "E2E_PUBLIC_DATASET_NAME": content["public"].dataset.name,
        "E2E_PUBLIC_RECORDING_ID": str(content["public"].recording.id),
        "E2E_PUBLIC_CLIP_ID": str(content["public"].clip.id),
        "E2E_PUBLIC_DETECTION_ID": str(content["public"].detection.id),
        "E2E_PUBLIC_ANNOTATION_ID": str(content["public"].annotation.id),
        "E2E_PUBLIC_SEARCH_SESSION_ID": str(search_sessions["public"].id),
        "E2E_PUBLIC_EXPORTABLE_SEARCH_SESSION_ID": str(search_sessions["public_exportable"].id),
        "E2E_PUBLIC_TRUSTED_OVERLAY_ID": str(trusted_overlays["public"].id),
        "E2E_RESTRICTED_PROJECT_ID": str(projects["restricted"].id),
        "E2E_RESTRICTED_PROJECT_NAME": projects["restricted"].name,
        "E2E_RESTRICTED_SITE_ID": str(content["restricted"].site.id),
        "E2E_RESTRICTED_DATASET_ID": str(content["restricted"].dataset.id),
        "E2E_RESTRICTED_DATASET_NAME": content["restricted"].dataset.name,
        "E2E_RESTRICTED_RECORDING_ID": str(content["restricted"].recording.id),
        "E2E_RESTRICTED_CLIP_ID": str(content["restricted"].clip.id),
        "E2E_RESTRICTED_DETECTION_ID": str(content["restricted"].detection.id),
        "E2E_RESTRICTED_ANNOTATION_ID": str(content["restricted"].annotation.id),
        "E2E_RESTRICTED_SEARCH_SESSION_ID": str(search_sessions["restricted"].id),
        "E2E_RESTRICTED_EXPORTABLE_SEARCH_SESSION_ID": str(
            search_sessions["restricted_exportable"].id
        ),
        "E2E_RESTRICTED_TRUSTED_OVERLAY_ID": str(trusted_overlays["restricted"].id),
        "E2E_RESTRICTED_TRUSTED_LIFECYCLE_OVERLAY_ID": str(
            trusted_overlays["restricted_lifecycle"].id
        ),
        "E2E_RESTRICTED_TRUSTED_EXPIRED_OVERLAY_ID": str(trusted_overlays["restricted_expired"].id),
    }
    env.update({API_KEY_ENV_NAMES[role]: raw_api_keys[role] for role in USER_ROLES})
    return env


async def _seed(prefix: str, password: str) -> dict[str, Any]:
    """Seed all E2E permission fixtures in a single transaction."""
    async with AsyncSessionLocal() as session:
        try:
            users: dict[str, User] = {}
            totp_secrets: dict[str, str] = {}
            for role in USER_ROLES:
                user, totp_secret = await _upsert_user(
                    session,
                    prefix=prefix,
                    role=role,
                    password=password,
                )
                users[role] = user
                totp_secrets[role] = totp_secret
                await _clear_two_factor_failure_state(user)

            api_keys: dict[str, ApiKey] = {}
            raw_api_keys: dict[str, str] = {}
            for role in USER_ROLES:
                api_key, raw_key = await _upsert_api_key(
                    session,
                    prefix=prefix,
                    role=role,
                    user=users[role],
                )
                api_keys[role] = api_key
                raw_api_keys[role] = raw_key

            projects = {
                "public": await _upsert_project(
                    session,
                    prefix=prefix,
                    owner=users["owner"],
                    kind="public",
                    visibility=ProjectVisibility.PUBLIC,
                    restricted_config={},
                ),
                "restricted": await _upsert_project(
                    session,
                    prefix=prefix,
                    owner=users["owner"],
                    kind="restricted",
                    visibility=ProjectVisibility.RESTRICTED,
                    restricted_config=RESTRICTED_CONFIG,
                ),
            }

            for project in projects.values():
                for role, member_role in MEMBERSHIP_ROLES.items():
                    await _upsert_membership(
                        session,
                        project=project,
                        user=users[role],
                        role=member_role,
                        invited_by=users["owner"],
                    )

            content = {
                kind: await _upsert_content(
                    session,
                    prefix=prefix,
                    owner=users["owner"],
                    project=project,
                    kind=kind,
                )
                for kind, project in projects.items()
            }

            search_sessions = {
                kind: await _upsert_search_session(
                    session,
                    prefix=prefix,
                    owner=users["owner"],
                    project=project,
                    content=content[kind],
                    kind=kind,
                )
                for kind, project in projects.items()
            }
            search_sessions.update(
                {
                    f"{kind}_exportable": await _upsert_exportable_search_session(
                        session,
                        prefix=prefix,
                        owner=users["owner"],
                        project=project,
                        content=content[kind],
                        kind=kind,
                    )
                    for kind, project in projects.items()
                }
            )

            settings = get_settings()
            trusted_overlays = {
                kind: await _upsert_trusted_overlay(
                    session,
                    project=project,
                    trusted_user=users["trusted"],
                    granted_by=users["owner"],
                    email_hash_secret=settings.web_session_secret,
                )
                for kind, project in projects.items()
            }
            lifecycle_now = datetime.now(UTC)
            trusted_overlays["restricted_lifecycle"] = await _upsert_trusted_overlay(
                session,
                project=projects["restricted"],
                trusted_user=users["trusted_lifecycle"],
                granted_by=users["owner"],
                email_hash_secret=settings.web_session_secret,
                token_suffix="trusted-lifecycle-active",
            )
            trusted_overlays["restricted_expired"] = await _upsert_trusted_overlay(
                session,
                project=projects["restricted"],
                trusted_user=users["trusted_lifecycle"],
                granted_by=users["owner"],
                email_hash_secret=settings.web_session_secret,
                token_suffix="trusted-lifecycle-expired",
                status=ProjectTrustedStatus.EXPIRED,
                granted_at=lifecycle_now - timedelta(days=10),
                expires_at=lifecycle_now - timedelta(days=1),
            )

            await session.commit()

            # `session.commit()` expires all attributes (expire_on_commit=True),
            # so the `Project.license_record` relationship is unloaded. Eager-load
            # it here (awaited) before `_project_payload` reads `project.license`,
            # which dereferences the relationship; a lazy-load there would attempt
            # synchronous IO inside the async session and raise MissingGreenlet.
            for project in projects.values():
                await session.refresh(project, ["license_record"])

            return {
                "users": {
                    role: _user_payload(
                        user,
                        role=role,
                    )
                    for role, user in users.items()
                },
                "projects": {
                    kind: _project_payload(project, content[kind])
                    for kind, project in projects.items()
                },
                "search_sessions": {
                    kind: _search_session_payload(search_session)
                    for kind, search_session in search_sessions.items()
                },
                "api_keys": {
                    role: _api_key_payload(
                        api_key,
                        role=role,
                    )
                    for role, api_key in api_keys.items()
                },
                "trusted_overlays": {
                    kind: {
                        "id": str(overlay.id),
                        "project_id": str(overlay.project_id),
                        "user_id": str(overlay.user_id),
                        "invitation_id": str(overlay.invitation_id),
                        "status": overlay.status.value,
                        "granted_permissions": list(overlay.granted_permissions),
                    }
                    for kind, overlay in trusted_overlays.items()
                },
                "credentials": {
                    "password_env": "E2E_PASSWORD",
                    "totp_secret_env": {
                        role: f"E2E_{role.upper()}_TOTP_SECRET" for role in USER_ROLES
                    },
                },
                "env": _env_payload(
                    prefix=prefix,
                    password=password,
                    users=users,
                    totp_secrets=totp_secrets,
                    projects=projects,
                    content=content,
                    search_sessions=search_sessions,
                    trusted_overlays=trusted_overlays,
                    raw_api_keys=raw_api_keys,
                ),
            }
        except Exception:
            await session.rollback()
            raise


def _validate_args(args: argparse.Namespace) -> None:
    if not args.confirm:
        raise SystemExit("Refusing to run without --confirm. This script mutates the local DB.")
    if len(args.password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(
            f"--password must be at least {MIN_PASSWORD_LENGTH} characters "
            f"(got {len(args.password)})"
        )
    if not args.prefix.strip():
        raise SystemExit("--prefix must not be empty")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    args = _build_parser().parse_args(argv)

    try:
        _validate_args(args)
        _validate_environment_safety(
            allow_non_local_database=args.allow_non_local_database,
        )
        payload = asyncio.run(_seed(prefix=args.prefix.strip(), password=args.password))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - top-level CLI guard
        logger.exception("seed_e2e_permissions failed: %s", exc)
        return 1

    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI invocation
    raise SystemExit(main())
