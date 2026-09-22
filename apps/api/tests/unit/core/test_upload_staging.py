"""Unit tests for local resumable-upload staging."""

from __future__ import annotations

import stat
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from echoroo.core import upload_staging


@pytest.fixture
def staging_root(monkeypatch: pytest.MonkeyPatch, tmp_path):
    root = tmp_path / "staging"
    monkeypatch.setattr(
        upload_staging,
        "get_settings",
        lambda: SimpleNamespace(UPLOAD_STAGING_DIR=str(root)),
    )
    return root


def test_first_chunk_creates_private_directory_and_file(staging_root) -> None:
    session_id = uuid4()
    file_id = uuid4()
    data = b"first chunk"

    result = upload_staging.append_chunk(
        session_id,
        file_id,
        offset=0,
        data=data,
        declared_size=len(data),
    )

    assert result == len(data)
    assert stat.S_IMODE(upload_staging.session_dir(session_id).stat().st_mode) == 0o700
    assert stat.S_IMODE(upload_staging.part_path(session_id, file_id).stat().st_mode) == 0o600


def test_second_chunk_appends_and_reports_staged_size(staging_root) -> None:
    session_id = uuid4()
    file_id = uuid4()

    assert upload_staging.append_chunk(
        session_id, file_id, offset=0, data=b"first", declared_size=12
    ) == 5
    assert upload_staging.append_chunk(
        session_id, file_id, offset=5, data=b" second", declared_size=12
    ) == 12

    assert upload_staging.staged_size(session_id, file_id) == 12
    assert upload_staging.part_path(session_id, file_id).read_bytes() == b"first second"


def test_wrong_offset_leaves_file_unchanged(staging_root) -> None:
    session_id = uuid4()
    file_id = uuid4()
    upload_staging.append_chunk(
        session_id, file_id, offset=0, data=b"existing", declared_size=20
    )

    with pytest.raises(upload_staging.StagingOffsetError) as error:
        upload_staging.append_chunk(
            session_id, file_id, offset=2, data=b"new", declared_size=20
        )

    assert error.value.expected_offset == 8
    assert upload_staging.part_path(session_id, file_id).read_bytes() == b"existing"


def test_retried_chunk_is_rejected_and_never_duplicated(staging_root) -> None:
    session_id = uuid4()
    file_id = uuid4()
    upload_staging.append_chunk(
        session_id, file_id, offset=0, data=b"chunk", declared_size=10
    )

    with pytest.raises(upload_staging.StagingOffsetError) as error:
        upload_staging.append_chunk(
            session_id, file_id, offset=0, data=b"chunk", declared_size=10
        )

    assert error.value.expected_offset == 5
    assert upload_staging.part_path(session_id, file_id).read_bytes() == b"chunk"


def test_exceeding_declared_size_leaves_file_unchanged(staging_root) -> None:
    session_id = uuid4()
    file_id = uuid4()
    upload_staging.append_chunk(
        session_id, file_id, offset=0, data=b"ab", declared_size=3
    )

    with pytest.raises(upload_staging.StagingSizeError):
        upload_staging.append_chunk(
            session_id, file_id, offset=2, data=b"too long", declared_size=3
        )

    assert upload_staging.part_path(session_id, file_id).read_bytes() == b"ab"


def test_chunk_can_reach_declared_size_exactly(staging_root) -> None:
    session_id = uuid4()
    file_id = uuid4()

    assert upload_staging.append_chunk(
        session_id, file_id, offset=0, data=b"exact", declared_size=5
    ) == 5
    assert upload_staging.staged_size(session_id, file_id) == 5


def test_truncate_to_shrinks_and_validates_bounds(staging_root) -> None:
    session_id = uuid4()
    file_id = uuid4()
    upload_staging.append_chunk(
        session_id, file_id, offset=0, data=b"abcdef", declared_size=6
    )

    upload_staging.truncate_to(session_id, file_id, 3)
    assert upload_staging.part_path(session_id, file_id).read_bytes() == b"abc"

    with pytest.raises(ValueError):
        upload_staging.truncate_to(session_id, file_id, -1)
    with pytest.raises(ValueError):
        upload_staging.truncate_to(session_id, file_id, 4)

    missing_file_id = uuid4()
    upload_staging.truncate_to(session_id, missing_file_id, 99)
    assert upload_staging.staged_size(session_id, missing_file_id) == 0


def test_remove_session_deletes_directory_and_is_idempotent(staging_root) -> None:
    session_id = uuid4()
    upload_staging.append_chunk(
        session_id, uuid4(), offset=0, data=b"data", declared_size=4
    )

    upload_staging.remove_session(session_id)
    assert not upload_staging.session_dir(session_id).exists()
    upload_staging.remove_session(session_id)


def test_list_staged_sessions_only_returns_uuid_directories(staging_root) -> None:
    first = uuid4()
    second = uuid4()
    upload_staging.session_dir(first).mkdir(parents=True)
    upload_staging.session_dir(second).mkdir(parents=True)
    (staging_root / "not-a-uuid").mkdir()
    (staging_root / "a-file").write_text("ignored")

    assert set(upload_staging.list_staged_sessions()) == {first, second}


def test_part_path_requires_uuid_session_id(staging_root) -> None:
    with pytest.raises(TypeError):
        upload_staging.part_path("not-a-uuid", UUID(int=0))  # type: ignore[arg-type]
