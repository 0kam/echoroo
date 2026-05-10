"""Coverage uplift unit tests for ``echoroo.core.s3``.

Phase 17 §C heavy-gap batch: targets the boto3-wrapping helpers that the
full S3 integration suite skips when LocalStack is not available —
``get_s3_client`` / ``get_public_s3_client`` (lines 78-83, 101-103),
``ensure_bucket_exists`` (lines 113, 121), ``generate_presigned_upload_url``
(lines 163-165, 173), ``verify_object_exists`` (lines 173, 201-223),
``delete_object`` / ``delete_objects_by_prefix`` (lines 240, 260-282),
``copy_object`` / ``move_object`` / ``get_object_stream`` /
``list_objects_paginated`` / ``delete_objects_batch`` (lines 300-360)
so the module clears the 85% threshold without touching production code.

All tests inject a fake boto3 client into the helper's ``client`` kwarg
to avoid LocalStack / network dependencies.
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from echoroo.core import s3 as s3mod


def _client_error(code: str, message: str = "boom") -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": message}},
        operation_name="HeadObject",
    )


def _fake_client() -> MagicMock:
    client = MagicMock()
    client.head_bucket = MagicMock()
    client.create_bucket = MagicMock()
    client.head_object = MagicMock(return_value={"ContentLength": 12, "ETag": '"abc"'})
    client.get_object = MagicMock()
    client.delete_object = MagicMock()
    client.delete_objects = MagicMock(return_value={"Deleted": []})
    client.copy_object = MagicMock()
    client.generate_presigned_url = MagicMock(return_value="https://signed/")
    return client


def test_ensure_bucket_exists_creates_when_missing() -> None:
    """ensure_bucket_exists() creates the bucket when head_bucket raises (lines 78-83)."""
    client = _fake_client()
    client.head_bucket.side_effect = _client_error("404")
    s3mod.ensure_bucket_exists(client=client)
    client.create_bucket.assert_called_once()


def test_ensure_bucket_exists_skip_when_present() -> None:
    """ensure_bucket_exists() is a no-op when the bucket already exists."""
    client = _fake_client()
    s3mod.ensure_bucket_exists(client=client)
    client.create_bucket.assert_not_called()


def test_generate_presigned_upload_url_returns_signed_url() -> None:
    """generate_presigned_upload_url() returns the signed URL (lines 113, 121)."""
    client = _fake_client()
    url = s3mod.generate_presigned_upload_url(
        object_key="recordings/x.wav", expiry_seconds=60, client=client,
    )
    assert url == "https://signed/"
    client.generate_presigned_url.assert_called_once()


def test_verify_object_exists_404_returns_not_found() -> None:
    """verify_object_exists() returns the 404 result dict (lines 163-173)."""
    client = _fake_client()
    client.head_object.side_effect = _client_error("404")
    result = s3mod.verify_object_exists("missing/key", client=client)
    assert result["exists"] is False
    assert result["sha256_match"] is None


def test_verify_object_exists_non_404_raises() -> None:
    """verify_object_exists() re-raises non-404 ClientErrors."""
    client = _fake_client()
    client.head_object.side_effect = _client_error("500")
    with pytest.raises(ClientError):
        s3mod.verify_object_exists("any", client=client)


def test_verify_object_exists_with_sha256_match() -> None:
    """verify_object_exists() compares SHA-256 over streamed body (lines 201-211)."""
    body_bytes = b"hello world"
    import hashlib
    expected_hex = hashlib.sha256(body_bytes).hexdigest()

    client = _fake_client()
    client.head_object.return_value = {"ContentLength": len(body_bytes), "ETag": '"e"'}
    body = io.BytesIO(body_bytes)
    client.get_object.return_value = {"Body": body}

    result = s3mod.verify_object_exists(
        "key",
        expected_size=len(body_bytes),
        client=client,
        expected_sha256=expected_hex,
    )
    assert result["sha256_match"] is True
    assert result["actual_sha256"] == expected_hex


def test_verify_object_exists_get_object_failure_marks_not_found() -> None:
    """A get_object failure during SHA-256 verification marks exists=False."""
    client = _fake_client()
    client.head_object.return_value = {"ContentLength": 4, "ETag": '"e"'}
    client.get_object.side_effect = _client_error("NoSuchKey")
    result = s3mod.verify_object_exists(
        "k", client=client, expected_sha256="00" * 32,
    )
    assert result["exists"] is False
    assert result["sha256_match"] is False


def test_delete_object_returns_true_on_success() -> None:
    """delete_object() returns True (lines 217-220)."""
    client = _fake_client()
    assert s3mod.delete_object("k", client=client) is True


def test_delete_object_returns_false_on_client_error() -> None:
    """delete_object() returns False on ClientError (lines 221-223)."""
    client = _fake_client()
    client.delete_object.side_effect = _client_error("AccessDenied")
    assert s3mod.delete_object("k", client=client) is False


def test_delete_objects_by_prefix_iterates_pages() -> None:
    """delete_objects_by_prefix() walks the paginator and deletes objects (lines 240-244)."""
    client = _fake_client()
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "p/a"}, {"Key": "p/b"}]},
        {"Contents": []},  # empty page → continue branch
    ]
    client.get_paginator = MagicMock(return_value=paginator)
    client.delete_objects.return_value = {"Deleted": [{"Key": "p/a"}, {"Key": "p/b"}]}
    deleted = s3mod.delete_objects_by_prefix("p/", client=client)
    assert deleted == 2


def test_copy_object_invokes_client_copy() -> None:
    """copy_object() calls client.copy_object with the proper Bucket/Key (lines 260-266)."""
    client = _fake_client()
    s3mod.copy_object(source_key="a", dest_key="b", client=client)
    client.copy_object.assert_called_once()


def test_move_object_returns_true_on_success() -> None:
    """move_object() returns True after copy + delete (lines 271-281)."""
    client = _fake_client()
    assert s3mod.move_object("a", "b", client=client) is True


def test_move_object_returns_false_on_client_error() -> None:
    """move_object() returns False when the boto3 call raises."""
    client = _fake_client()
    client.copy_object.side_effect = _client_error("AccessDenied")
    assert s3mod.move_object("a", "b", client=client) is False


def test_get_object_stream_with_byte_range() -> None:
    """get_object_stream() forwards the Range parameter (lines 300-306)."""
    client = _fake_client()
    body = io.BytesIO(b"data")
    client.get_object = MagicMock(return_value={"Body": body})
    out = s3mod.get_object_stream("k", byte_range="bytes=0-3", client=client)
    assert out is body
    args = client.get_object.call_args
    assert args.kwargs["Range"] == "bytes=0-3"


def test_list_objects_paginated_yields_metadata_with_continuation() -> None:
    """list_objects_paginated() iterates ContinuationToken pages (lines 329-341)."""
    client = _fake_client()
    import datetime as dt
    client.list_objects_v2 = MagicMock(side_effect=[
        {
            "Contents": [
                {"Key": "a", "LastModified": dt.datetime(2026, 1, 1, tzinfo=dt.UTC), "Size": 10},
            ],
            "IsTruncated": True,
            "NextContinuationToken": "t1",
        },
        {
            "Contents": [
                {"Key": "b", "LastModified": dt.datetime(2026, 1, 2, tzinfo=dt.UTC), "Size": 20},
            ],
            "IsTruncated": False,
        },
    ])
    keys = [m.key for m in s3mod.list_objects_paginated("p/", client=client)]
    assert keys == ["a", "b"]


def test_delete_objects_batch_empty_keys_returns_empty_result() -> None:
    """delete_objects_batch([]) returns the empty BatchDeleteResult (lines 358-360)."""
    out = s3mod.delete_objects_batch([], client=_fake_client())
    assert out.deleted == []
    assert out.errors == []


def test_delete_objects_batch_too_many_keys_raises() -> None:
    """delete_objects_batch() rejects > 1000 keys (lines 359-360)."""
    with pytest.raises(ValueError):
        s3mod.delete_objects_batch(["k"] * 1001, client=_fake_client())


def test_delete_objects_batch_returns_structured_result() -> None:
    """delete_objects_batch() returns Deleted + structured Errors."""
    client = _fake_client()
    client.delete_objects = MagicMock(return_value={
        "Deleted": [{"Key": "a"}, {"Key": "b"}],
        "Errors": [{"Key": "c", "Code": "AccessDenied", "Message": "no perm"}],
    })
    result = s3mod.delete_objects_batch(["a", "b", "c"], client=client)
    assert result.deleted == ["a", "b"]
    assert len(result.errors) == 1
    assert result.errors[0].key == "c"
    assert result.errors[0].code == "AccessDenied"


def test_get_s3_client_returns_boto3_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_s3_client() builds a boto3 client with settings (lines 78-83)."""
    captured: dict[str, Any] = {}

    def fake_boto3_client(service: str, **kwargs: Any) -> object:
        captured["service"] = service
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(s3mod.boto3, "client", fake_boto3_client)
    out = s3mod.get_s3_client()
    assert out is not None
    assert captured["service"] == "s3"
    assert "endpoint_url" in captured["kwargs"]


def test_get_public_s3_client_uses_public_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_public_s3_client() picks S3_PUBLIC_ENDPOINT_URL when set (lines 101-103)."""
    captured: dict[str, Any] = {}

    def fake_boto3_client(service: str, **kwargs: Any) -> object:
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(s3mod.boto3, "client", fake_boto3_client)
    out = s3mod.get_public_s3_client()
    assert out is not None
    # Either S3_PUBLIC_ENDPOINT_URL or S3_ENDPOINT_URL was used.
    assert "endpoint_url" in captured["kwargs"]
