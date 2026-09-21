import hashlib
import hmac
import io
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from botocore.exceptions import ClientError

from echoroo.services.audit_service import _build_canonical_row
from echoroo.workers import audit_log_export as mod

_KEY = b"unit-test-chain-key"


def _fake_mac(prev_hash: str, canonical_row: bytes) -> str:
    return hmac.new(_KEY, prev_hash.encode("ascii") + canonical_row, hashlib.sha256).hexdigest()


def _row(
    created_at: datetime,
    *,
    prev_hash: str = "0" * 64,
    project: bool = True,
    action: str = "x.y",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-000000000001",
        "created_at": created_at,
        "actor_user_id_hash": "a" * 64,
        "action": action,
        "detail": {"k": "v"},
        "request_id": "req-1",
        "ip_hash": "b" * 64,
        "user_agent_hash": "c" * 64,
        "before": None,
        "after": {"n": 1},
        "prev_hash": prev_hash,
    }
    if project:
        row["project_id"] = "11111111-1111-1111-1111-111111111111"
    # Signed with the WRITER's canonicaliser (audit_service), not the
    # verifier's, so a drift between the two breaks these tests.
    canonical = _build_canonical_row(
        created_at=created_at,
        actor_user_id_hash=row["actor_user_id_hash"],
        action=action,
        project_id=UUID(row["project_id"]) if project else None,
        request_id=row["request_id"],
        ip_hash=row["ip_hash"],
        user_agent_hash=row["user_agent_hash"],
        detail=row["detail"],
        before=row["before"],
        after=row["after"],
    )
    row["row_hash"] = _fake_mac(prev_hash, canonical)
    return row


def _chain(*specs: tuple[datetime, str], project: bool = True) -> list[dict[str, Any]]:
    """Build linked rows: each row's prev_hash is the previous row's row_hash."""
    rows: list[dict[str, Any]] = []
    prev = "0" * 64
    for index, (created_at, action) in enumerate(specs):
        row = _row(created_at, prev_hash=prev, project=project, action=action)
        row["id"] = f"00000000-0000-0000-0000-{index:012d}"
        rows.append(row)
        prev = row["row_hash"]
    return rows


class _FakeS3:
    """In-memory stand-in for the boto3 client methods core/s3 uses."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[dict[str, Any]] = []

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        return {"ContentLength": len(self.objects[Key])}

    def put_object(self, **kwargs: Any) -> None:
        self.put_calls.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, *, Bucket: str, Key: str, **_: Any) -> dict[str, Any]:  # noqa: N803
        return {"Body": io.BytesIO(self.objects[Key])}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Provide in-memory storage, database access, and audit MACs."""
    monkeypatch.setattr(mod, "compute_audit_chain_hash", _fake_mac)

    s3 = _FakeS3()
    monkeypatch.setattr("echoroo.core.s3.get_s3_client", lambda: s3)

    class _SessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: Any) -> None:
            return None

    def factory() -> _SessionContext:
        return _SessionContext()

    monkeypatch.setattr(
        "echoroo.workers.db_utils.get_worker_engine_and_session_factory",
        lambda: (None, factory),
    )

    rows_by_table: dict[str, list[dict[str, Any]]] = {
        "project_audit_log": [],
        "platform_audit_log": [],
    }

    async def fake_afetch_rows(
        session: Any,
        table: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        del session
        rows = rows_by_table[table]
        return sorted(
            [
                row
                for row in rows
                if (start is None or row["created_at"] >= start)
                and (end is None or row["created_at"] < end)
            ],
            key=lambda row: row["created_at"],
        )

    monkeypatch.setattr(mod, "_afetch_rows", fake_afetch_rows)

    async def fake_afetch_prev_hash(session: Any, table: str, *, before: datetime) -> str:
        del session
        earlier = sorted(
            (row for row in rows_by_table[table] if row["created_at"] < before),
            key=lambda row: row["created_at"],
        )
        return earlier[-1]["row_hash"] if earlier else "0" * 64

    monkeypatch.setattr(mod, "_afetch_prev_hash", fake_afetch_prev_hash)

    lock = SimpleNamespace(available=True)

    async def fake_try_export_lock(session: Any) -> bool:
        del session
        return lock.available

    monkeypatch.setattr(mod, "_try_export_lock", fake_try_export_lock)
    return SimpleNamespace(s3=s3, rows_by_table=rows_by_table, lock=lock)


NOW = "2026-09-21T03:00:00+00:00"


def test_week_bounds() -> None:
    assert mod._week_bounds(2026, 38) == (
        datetime(2026, 9, 14, tzinfo=UTC),
        datetime(2026, 9, 21, tzinfo=UTC),
    )


def test_closed_weeks_excludes_current_week() -> None:
    assert mod._closed_weeks(datetime(2026, 9, 21, 3, tzinfo=UTC), 2) == [
        (2026, 37),
        (2026, 38),
    ]
    assert mod._closed_weeks(datetime(2026, 9, 27, 23, 59, tzinfo=UTC), 2) == [
        (2026, 37),
        (2026, 38),
    ]


def test_closed_weeks_crosses_iso_year() -> None:
    assert mod._closed_weeks(datetime(2027, 1, 4, tzinfo=UTC), 1) == [(2026, 53)]


def test_week_object_key() -> None:
    assert mod._week_object_key("project_audit_log", 2026, 5) == (
        "audit-log/project_audit_log/2026/05.ndjson"
    )


def test_export_archives_closed_week_and_skips_current(env: Any) -> None:
    env.rows_by_table["project_audit_log"] = _chain(
        (datetime(2026, 9, 15, 12, tzinfo=UTC), "x.y"),
        (datetime(2026, 9, 21, 1, tzinfo=UTC), "x.y"),
    )

    summary = mod.export_weekly(now_iso=NOW)

    assert len(env.s3.put_calls) == 1
    assert env.s3.put_calls[0]["Key"] == "audit-log/project_audit_log/2026/38.ndjson"
    assert summary["archives"] == [
        {
            "table": "project_audit_log",
            "key": "audit-log/project_audit_log/2026/38.ndjson",
            "row_count": 1,
        }
    ]
    stored = env.s3.objects["audit-log/project_audit_log/2026/38.ndjson"]
    assert len(stored.splitlines()) == 1
    assert "ObjectLockMode" not in env.s3.put_calls[0]
    assert "ObjectLockRetainUntilDate" not in env.s3.put_calls[0]
    assert env.s3.put_calls[0]["ContentType"] == "application/x-ndjson"


def test_export_is_write_once(env: Any) -> None:
    env.rows_by_table["project_audit_log"] = [_row(datetime(2026, 9, 15, tzinfo=UTC))]

    mod.export_weekly(now_iso=NOW)
    key = "audit-log/project_audit_log/2026/38.ndjson"
    first_body = env.s3.objects[key]

    summary = mod.export_weekly(now_iso=NOW)

    assert summary["archives"] == []
    assert len(env.s3.put_calls) == 1
    assert env.s3.objects[key] == first_body


def test_late_row_in_archived_week_fails_visibly_and_never_overwrites(env: Any) -> None:
    rows = _chain((datetime(2026, 9, 15, tzinfo=UTC), "x.y"), (datetime(2026, 9, 16, tzinfo=UTC), "x.z"))
    env.rows_by_table["project_audit_log"] = rows[:1]
    mod.export_weekly(now_iso=NOW)
    key = "audit-log/project_audit_log/2026/38.ndjson"
    first_body = env.s3.objects[key]

    env.rows_by_table["project_audit_log"] = rows  # a row commits after the export
    with pytest.raises(mod.AuditChainMismatchError, match="38.ndjson"):
        mod.export_weekly(now_iso=NOW)

    assert len(env.s3.put_calls) == 1
    assert env.s3.objects[key] == first_body


def test_replaced_archive_is_detected_on_next_run(env: Any) -> None:
    env.rows_by_table["project_audit_log"] = [_row(datetime(2026, 9, 15, tzinfo=UTC))]
    mod.export_weekly(now_iso=NOW)
    key = "audit-log/project_audit_log/2026/38.ndjson"
    env.s3.objects[key] = b""

    with pytest.raises(mod.AuditChainMismatchError, match="38.ndjson"):
        mod.export_weekly(now_iso=NOW)

    assert len(env.s3.put_calls) == 1


def test_archive_without_live_rows_fails(env: Any) -> None:
    env.s3.objects["audit-log/project_audit_log/2026/38.ndjson"] = b"{}\n"

    with pytest.raises(mod.AuditChainMismatchError, match="38.ndjson"):
        mod.export_weekly(now_iso=NOW)

    assert env.s3.put_calls == []


def test_concurrent_run_is_skipped(env: Any) -> None:
    env.rows_by_table["project_audit_log"] = [_row(datetime(2026, 9, 15, tzinfo=UTC))]
    env.lock.available = False

    summary = mod.export_weekly(now_iso=NOW)

    assert "skipped" in summary
    assert env.s3.put_calls == []


def test_naive_now_is_utc(env: Any) -> None:
    env.rows_by_table["project_audit_log"] = [_row(datetime(2026, 9, 15, tzinfo=UTC))]

    mod.export_weekly(now_iso="2026-09-21T03:00:00")

    assert [call["Key"] for call in env.s3.put_calls] == [
        "audit-log/project_audit_log/2026/38.ndjson"
    ]


def test_bootstrap_rows_are_archived_without_a_mac(env: Any) -> None:
    genesis = _row(datetime(2026, 9, 14, 1, tzinfo=UTC), action="genesis")
    genesis["row_hash"] = "0" * 64
    follower = _row(datetime(2026, 9, 14, 2, tzinfo=UTC), prev_hash="0" * 64)
    follower["id"] = "00000000-0000-0000-0000-000000000002"
    env.rows_by_table["project_audit_log"] = [genesis, follower]

    mod.export_weekly(now_iso=NOW)

    key = "audit-log/project_audit_log/2026/38.ndjson"
    assert mod.verify_archive(key, include_project_id=True) == 2


def test_zero_hash_is_not_accepted_for_ordinary_actions(env: Any) -> None:
    forged = _row(datetime(2026, 9, 15, tzinfo=UTC), action="x.y")
    forged["row_hash"] = "0" * 64
    env.rows_by_table["project_audit_log"] = [forged]

    with pytest.raises(mod.AuditChainMismatchError):
        mod.export_weekly(now_iso=NOW)

    assert env.s3.put_calls == []


@pytest.mark.parametrize("damage", ["drop_interior", "reorder", "empty", "malformed"])
def test_verify_archive_detects_structural_damage(env: Any, damage: str) -> None:
    env.rows_by_table["project_audit_log"] = _chain(
        (datetime(2026, 9, 15, tzinfo=UTC), "a.a"),
        (datetime(2026, 9, 16, tzinfo=UTC), "b.b"),
        (datetime(2026, 9, 17, tzinfo=UTC), "c.c"),
    )
    mod.export_weekly(now_iso=NOW)
    key = "audit-log/project_audit_log/2026/38.ndjson"
    assert mod.verify_archive(key, include_project_id=True) == 3
    lines = env.s3.objects[key].splitlines(keepends=True)
    env.s3.objects[key] = {
        "drop_interior": lines[0] + lines[2],
        "reorder": lines[1] + lines[0] + lines[2],
        "empty": b"",
        "malformed": b"not json\n",
    }[damage]

    with pytest.raises(mod.AuditArchiveMismatchError):
        mod.verify_archive(key, include_project_id=True)


def test_afetch_rows_uses_a_half_open_window() -> None:
    """The real query: inclusive start, exclusive end, deterministic order."""
    import asyncio

    captured: dict[str, Any] = {}

    class _Result:
        def mappings(self) -> Any:
            return SimpleNamespace(all=lambda: [])

    class _Session:
        async def execute(self, stmt: Any, params: dict[str, Any]) -> _Result:
            captured["sql"] = " ".join(str(stmt).split())
            captured["params"] = params
            return _Result()

    start, end = mod._week_bounds(2026, 38)
    asyncio.run(mod._afetch_rows(_Session(), "platform_audit_log", start=start, end=end))

    assert "created_at >= :start AND created_at < :end" in captured["sql"]
    assert "ORDER BY created_at ASC, id ASC" in captured["sql"]
    assert "project_id" not in captured["sql"]
    assert captured["params"] == {"start": start, "end": end}


def test_export_catches_up_missed_week(env: Any) -> None:
    env.rows_by_table["project_audit_log"] = _chain(
        (datetime(2026, 9, 1, tzinfo=UTC), "x.y"),
        (datetime(2026, 9, 15, tzinfo=UTC), "x.y"),
    )

    mod.export_weekly(now_iso=NOW)

    keys = {call["Key"] for call in env.s3.put_calls}
    assert keys == {
        "audit-log/project_audit_log/2026/36.ndjson",
        "audit-log/project_audit_log/2026/38.ndjson",
    }
    assert "audit-log/project_audit_log/2026/37.ndjson" not in env.s3.objects


def test_export_ignores_weeks_outside_catch_up_window(env: Any) -> None:
    env.rows_by_table["project_audit_log"] = [_row(datetime(2026, 7, 15, tzinfo=UTC))]

    mod.export_weekly(now_iso=NOW)

    assert env.s3.put_calls == []


def test_db_chain_mismatch_is_never_archived(env: Any) -> None:
    row = _row(datetime(2026, 9, 15, tzinfo=UTC))
    row["row_hash"] = "f" * 64
    env.rows_by_table["project_audit_log"] = [row]

    with pytest.raises(mod.AuditChainMismatchError, match="38.ndjson"):
        mod.export_weekly(now_iso=NOW)

    assert env.s3.put_calls == []


def test_broken_week_does_not_block_clean_weeks(env: Any) -> None:
    """One bad week fails the task, but every clean week is still archived."""
    rows = _chain((datetime(2026, 9, 8, tzinfo=UTC), "x.y"), (datetime(2026, 9, 15, tzinfo=UTC), "x.y"))
    rows[0]["action"] = "x.edited"  # W37 fails its MAC; links to W38 stay intact
    env.rows_by_table["project_audit_log"] = rows
    env.rows_by_table["platform_audit_log"] = [
        _row(datetime(2026, 9, 15, tzinfo=UTC), project=False)
    ]

    with pytest.raises(mod.AuditChainMismatchError, match="37.ndjson"):
        mod.export_weekly(now_iso=NOW)

    assert sorted(call["Key"] for call in env.s3.put_calls) == [
        "audit-log/platform_audit_log/2026/38.ndjson",
        "audit-log/project_audit_log/2026/38.ndjson",
    ]


def test_verify_archive_detects_tampering(env: Any) -> None:
    env.rows_by_table["project_audit_log"] = [_row(datetime(2026, 9, 15, tzinfo=UTC))]
    mod.export_weekly(now_iso=NOW)
    key = "audit-log/project_audit_log/2026/38.ndjson"

    assert mod.verify_archive(key, include_project_id=True) == 1
    env.s3.objects[key] = env.s3.objects[key].replace(b"x.y", b"x.z")

    with pytest.raises(mod.AuditArchiveMismatchError):
        mod.verify_archive(key, include_project_id=True)


def test_platform_table_roundtrip(env: Any) -> None:
    env.rows_by_table["platform_audit_log"] = [
        _row(datetime(2026, 9, 15, tzinfo=UTC), project=False)
    ]

    mod.export_weekly(now_iso=NOW)

    key = "audit-log/platform_audit_log/2026/38.ndjson"
    assert mod.verify_archive(key, include_project_id=False) == 1


def test_object_exists_propagates_non_404() -> None:
    class _DeniedClient:
        def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
            raise ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadObject")

    from echoroo.core.s3 import object_exists

    with pytest.raises(ClientError):
        object_exists("k", client=_DeniedClient())


def test_forged_bootstrap_row_cannot_replace_a_week(env: Any) -> None:
    """Zero-hash rows are only reachable at the start of the chain."""
    rows = _chain((datetime(2026, 9, 8, tzinfo=UTC), "x.y"), (datetime(2026, 9, 15, tzinfo=UTC), "x.y"))
    forged = _row(datetime(2026, 9, 15, tzinfo=UTC), action="platform.wipe_executed")
    forged["row_hash"] = "0" * 64
    env.rows_by_table["project_audit_log"] = [rows[0], forged]  # W38 replaced wholesale

    with pytest.raises(mod.AuditChainMismatchError, match="38.ndjson"):
        mod.export_weekly(now_iso=NOW)

    assert [call["Key"] for call in env.s3.put_calls] == [
        "audit-log/project_audit_log/2026/37.ndjson"
    ]


def test_storage_failure_on_one_week_does_not_block_the_others(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.rows_by_table["project_audit_log"] = _chain(
        (datetime(2026, 9, 8, tzinfo=UTC), "x.y"), (datetime(2026, 9, 15, tzinfo=UTC), "x.y")
    )
    real_read = mod._read_archive

    def flaky_read(key: str) -> bytes | None:
        if key.endswith("/37.ndjson"):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "GetObject")
        return real_read(key)

    monkeypatch.setattr(mod, "_read_archive", flaky_read)

    with pytest.raises(mod.AuditChainMismatchError, match="37.ndjson"):
        mod.export_weekly(now_iso=NOW)

    assert [call["Key"] for call in env.s3.put_calls] == [
        "audit-log/project_audit_log/2026/38.ndjson"
    ]


def test_verify_archive_rejects_rows_outside_the_keys_week(env: Any) -> None:
    env.rows_by_table["project_audit_log"] = [_row(datetime(2026, 9, 15, tzinfo=UTC))]
    mod.export_weekly(now_iso=NOW)
    good = "audit-log/project_audit_log/2026/38.ndjson"
    copied = "audit-log/project_audit_log/2026/37.ndjson"
    env.s3.objects[copied] = env.s3.objects[good]

    with pytest.raises(mod.AuditArchiveMismatchError, match="outside the ISO week"):
        mod.verify_archive(copied, include_project_id=True)


def test_verify_archive_anchors_to_the_preceding_archive(env: Any) -> None:
    rows = _chain((datetime(2026, 9, 8, tzinfo=UTC), "x.y"), (datetime(2026, 9, 15, tzinfo=UTC), "x.y"))
    env.rows_by_table["project_audit_log"] = rows
    mod.export_weekly(now_iso=NOW)
    key = "audit-log/project_audit_log/2026/38.ndjson"

    assert mod.verify_archive(key, include_project_id=True, expected_prev_hash=rows[0]["row_hash"]) == 1
    with pytest.raises(mod.AuditArchiveMismatchError, match="chain link broken"):
        mod.verify_archive(key, include_project_id=True, expected_prev_hash="f" * 64)


def test_verify_archive_normalises_malformed_field_types(env: Any) -> None:
    key = "audit-log/project_audit_log/2026/38.ndjson"
    env.s3.objects[key] = (
        b'{"action":[],"created_at":"2026-09-15T00:00:00+00:00","row_hash":"x","prev_hash":"y"}\n'
    )

    with pytest.raises(mod.AuditArchiveMismatchError):
        mod.verify_archive(key, include_project_id=True)

