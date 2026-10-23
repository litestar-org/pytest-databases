"""Stdlib AWS Signature Version 4 bucket provisioning for S3-compatible emulators.

MinIO and RustFS create their default bucket through a signed ``PUT /<bucket>`` request so the fixtures need no S3
client library and no sidecar container.
"""

from __future__ import annotations

import hashlib
import hmac
import ssl
import time
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

__all__ = (
    "DEFAULT_REGION",
    "build_bucket_request",
    "create_s3_bucket",
    "derive_signing_key",
)

DEFAULT_REGION = "us-east-1"
EMPTY_PAYLOAD_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
SIGNED_HEADERS = "host;x-amz-content-sha256;x-amz-date"
BUCKET_EXISTS_CODES = ("BucketAlreadyOwnedByYou", "BucketAlreadyExists")
_RETRYABLE_HTTP_STATUS = 503
_RETRY_INTERVAL_SECONDS = 0.25


def derive_signing_key(secret_key: str, *, date_stamp: str, region: str, service: str) -> bytes:
    """Derive an AWS Signature Version 4 signing key.

    Args:
        secret_key: Secret access key.
        date_stamp: Request date as ``YYYYMMDD``.
        region: Signing region.
        service: Signing service name.

    Returns:
        The derived signing key.
    """
    key_date = hmac.new(f"AWS4{secret_key}".encode(), date_stamp.encode(), hashlib.sha256).digest()
    key_region = hmac.new(key_date, region.encode(), hashlib.sha256).digest()
    key_service = hmac.new(key_region, service.encode(), hashlib.sha256).digest()
    return hmac.new(key_service, b"aws4_request", hashlib.sha256).digest()


def build_bucket_request(
    method: str,
    endpoint_url: str,
    bucket_name: str,
    *,
    access_key: str,
    secret_key: str,
    region: str = DEFAULT_REGION,
    timestamp: datetime | None = None,
) -> Request:
    """Build a SigV4-signed path-style bucket request with an empty body.

    Args:
        method: HTTP method, such as ``PUT`` to create the bucket or ``HEAD`` to check that it exists.
        endpoint_url: ``http`` or ``https`` endpoint of the S3 service.
        bucket_name: Target bucket.
        access_key: Access key ID.
        secret_key: Secret access key.
        region: Signing region.
        timestamp: Signing time; defaults to the current UTC time.

    Returns:
        The signed request.

    Raises:
        ValueError: If ``endpoint_url`` is not an absolute ``http`` or ``https`` URL.
    """
    parsed = urlsplit(endpoint_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = f"S3 endpoint_url must be a valid http(s) URL, got {endpoint_url!r}"
        raise ValueError(msg)

    signed_at = (timestamp or datetime.now(UTC)).astimezone(UTC)
    amz_date = signed_at.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = signed_at.strftime("%Y%m%d")
    canonical_uri = f"/{bucket_name}"
    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    canonical_headers = f"host:{parsed.netloc}\nx-amz-content-sha256:{EMPTY_PAYLOAD_SHA256}\nx-amz-date:{amz_date}\n"
    canonical_request = f"{method}\n{canonical_uri}\n\n{canonical_headers}\n{SIGNED_HEADERS}\n{EMPTY_PAYLOAD_SHA256}"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )
    signing_key = derive_signing_key(secret_key, date_stamp=date_stamp, region=region, service="s3")
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers = {
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={SIGNED_HEADERS}, Signature={signature}"
        ),
        "Content-Length": "0",
        "x-amz-content-sha256": EMPTY_PAYLOAD_SHA256,
        "x-amz-date": amz_date,
    }
    return Request(f"{parsed.scheme}://{parsed.netloc}{canonical_uri}", data=None, method=method, headers=headers)


def create_s3_bucket(
    endpoint_url: str,
    bucket_name: str,
    *,
    access_key: str,
    secret_key: str,
    region: str = DEFAULT_REGION,
    timeout: float = 10,
) -> None:
    """Create a bucket idempotently with a SigV4-signed HTTP ``PUT``.

    An existing bucket is not an error. Transient HTTP ``503`` responses (such as RustFS waiting for storage quorum)
    are retried until ``timeout`` elapses. ``https`` endpoints are contacted without certificate verification because
    the target is a local emulator with a self-signed certificate.

    Args:
        endpoint_url: ``http`` or ``https`` endpoint of the S3 service.
        bucket_name: Bucket to create.
        access_key: Access key ID.
        secret_key: Secret access key.
        region: Signing region.
        timeout: Socket and retry deadline timeout in seconds.

    Raises:
        RuntimeError: If the service rejects the request or cannot be reached.
    """
    request = build_bucket_request(
        "PUT", endpoint_url, bucket_name, access_key=access_key, secret_key=secret_key, region=region
    )
    context = _unverified_ssl_context() if request.full_url.startswith("https:") else None
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urlopen(request, timeout=timeout, context=context) as response:
                status = response.status
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 409 and any(code in body for code in BUCKET_EXISTS_CODES):
                return
            if exc.code == _RETRYABLE_HTTP_STATUS and time.monotonic() < deadline:
                time.sleep(_RETRY_INTERVAL_SECONDS)
                continue
            msg = f"Failed to create bucket {bucket_name!r}: HTTP {exc.code} - {body}"
            raise RuntimeError(msg) from exc
        except (URLError, OSError) as exc:
            msg = f"Failed to create bucket {bucket_name!r} on {endpoint_url}: {exc}"
            raise RuntimeError(msg) from exc
        if status == _RETRYABLE_HTTP_STATUS and time.monotonic() < deadline:
            time.sleep(_RETRY_INTERVAL_SECONDS)
            continue
        if status not in {200, 204}:
            msg = f"Failed to create bucket {bucket_name!r}: HTTP {status}"
            raise RuntimeError(msg)
        return


def _unverified_ssl_context() -> ssl.SSLContext:
    """Return a TLS context that skips certificate and hostname verification.

    Returns:
        The TLS context.
    """
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context
