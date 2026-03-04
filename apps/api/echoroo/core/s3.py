"""S3-compatible storage client utility for file upload management."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from echoroo.core.settings import get_settings


def get_s3_client() -> Any:
    """Create and return an S3 client configured for S3-compatible storage."""
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
        config=Config(signature_version="s3v4"),
    )


def get_public_s3_client() -> Any:
    """Create and return an S3 client using the public endpoint URL.

    This client is intended for generating presigned URLs that are accessible
    from browsers. Uses S3_PUBLIC_ENDPOINT_URL when set, falling back to
    S3_ENDPOINT_URL.
    """
    settings = get_settings()
    endpoint_url = settings.S3_PUBLIC_ENDPOINT_URL or settings.S3_ENDPOINT_URL
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
        config=Config(signature_version="s3v4"),
    )


def ensure_bucket_exists(client: Any = None) -> None:
    """Create the bucket if it doesn't exist."""
    settings = get_settings()
    client = client or get_s3_client()
    try:
        client.head_bucket(Bucket=settings.S3_BUCKET)
    except ClientError:
        client.create_bucket(Bucket=settings.S3_BUCKET)


def generate_presigned_upload_url(
    object_key: str,
    expiry_seconds: int | None = None,
    client: Any = None,
) -> str:
    """Generate a presigned PUT URL for browser-direct upload.

    Args:
        object_key: S3 object key (must start with allowed prefix)
        expiry_seconds: URL expiry in seconds (default from settings)
        client: Optional S3 client instance

    Returns:
        Presigned URL string
    """
    settings = get_settings()
    client = client or get_s3_client()
    expiry = expiry_seconds or settings.S3_PRESIGNED_URL_EXPIRY

    # Only include Bucket and Key in presigned URL params.
    # ContentLength and ChecksumSHA256 are NOT included because they would
    # force the browser to send matching headers (content-length,
    # x-amz-checksum-sha256) which must exactly match the signed values.
    # Browsers set Content-Length automatically and don't know about
    # x-amz-checksum-sha256, causing signature mismatch errors that manifest
    # as CORS failures (S3 error responses lack CORS headers).
    # Integrity is verified server-side during the validation step instead.
    url: str = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.S3_BUCKET,
            "Key": object_key,
        },
        ExpiresIn=expiry,
    )
    return url


def verify_object_exists(
    object_key: str,
    expected_size: int | None = None,
    client: Any = None,
) -> dict[str, Any]:
    """Verify an object exists in S3 and optionally check its size.

    Returns:
        Dict with 'exists', 'size', 'etag', and 'size_match' keys
    """
    settings = get_settings()
    client = client or get_s3_client()
    try:
        response = client.head_object(Bucket=settings.S3_BUCKET, Key=object_key)
        actual_size = response["ContentLength"]
        result: dict[str, Any] = {
            "exists": True,
            "size": actual_size,
            "etag": response.get("ETag", "").strip('"'),
            "size_match": expected_size is None or actual_size == expected_size,
        }
        return result
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return {"exists": False, "size": 0, "etag": "", "size_match": False}
        raise


def delete_object(object_key: str, client: Any = None) -> bool:
    """Delete an object from S3."""
    settings = get_settings()
    client = client or get_s3_client()
    try:
        client.delete_object(Bucket=settings.S3_BUCKET, Key=object_key)
        return True
    except ClientError:
        return False


def delete_objects_by_prefix(prefix: str, client: Any = None) -> int:
    """Delete all objects with the given prefix.

    Returns:
        Count of deleted objects
    """
    settings = get_settings()
    client = client or get_s3_client()
    deleted_count = 0

    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.S3_BUCKET, Prefix=prefix):
        objects = page.get("Contents", [])
        if not objects:
            continue

        delete_request = {"Objects": [{"Key": obj["Key"]} for obj in objects]}
        response = client.delete_objects(Bucket=settings.S3_BUCKET, Delete=delete_request)
        deleted_count += len(response.get("Deleted", []))

    return deleted_count


def move_object(source_key: str, dest_key: str, client: Any = None) -> bool:
    """Move an object by copying then deleting the source."""
    settings = get_settings()
    client = client or get_s3_client()
    try:
        client.copy_object(
            Bucket=settings.S3_BUCKET,
            CopySource={"Bucket": settings.S3_BUCKET, "Key": source_key},
            Key=dest_key,
        )
        client.delete_object(Bucket=settings.S3_BUCKET, Key=source_key)
        return True
    except ClientError:
        return False


def get_object_stream(
    object_key: str,
    byte_range: str | None = None,
    client: Any = None,
) -> Any:
    """Get a streaming response for an S3 object.

    Args:
        object_key: S3 object key
        byte_range: Optional byte range (e.g., "bytes=0-65535")
        client: Optional S3 client instance

    Returns:
        StreamingBody object
    """
    settings = get_settings()
    client = client or get_s3_client()
    params: dict[str, Any] = {"Bucket": settings.S3_BUCKET, "Key": object_key}
    if byte_range:
        params["Range"] = byte_range
    response = client.get_object(**params)
    return response["Body"]
