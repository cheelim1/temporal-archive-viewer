"""Thin boto3 wrapper for browsing/fetching Temporal Cloud export objects."""

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    ProfileNotFound,
    ReadTimeoutError,
)

# Bounded timeouts + a capped retry count matter for two reasons: (1) without
# them, a single flaky call can block for minutes (default ~60s connect +
# 60s read, x3 retries), and across a scan's many sequential/concurrent
# calls that compounds badly; (2) Streamlit's own "Stop" button can only
# interrupt a script between Python bytecode steps — if the thread is stuck
# inside a blocking socket call with no timeout, Stop can't take effect
# until that call returns on its own. Capping it here is what makes Stop
# actually work as a cancel button for a stuck scan.
_CLIENT_CONFIG = Config(
    connect_timeout=10,
    read_timeout=20,
    retries={"max_attempts": 2, "mode": "standard"},
)


def get_client(profile: str | None = None, region: str | None = None):
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    if region:
        return session.client("s3", region_name=region, config=_CLIENT_CONFIG)
    return session.client("s3", config=_CLIENT_CONFIG)


def friendly_error(e: Exception) -> str:
    if isinstance(e, ProfileNotFound):
        return f"AWS profile not found: {e}. Check ~/.aws/config for the profile name."
    if isinstance(e, NoCredentialsError):
        return "No AWS credentials found. Set AWS_PROFILE or run `aws sso login --profile <name>`."
    if isinstance(e, (ConnectTimeoutError, ReadTimeoutError)):
        return "AWS request timed out. Check your network/VPN connection and try again."
    if isinstance(e, EndpointConnectionError):
        return "Could not reach AWS. Check your network/VPN connection, and the region setting."
    if isinstance(e, ClientError):
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("ExpiredToken", "ExpiredTokenException", "RequestExpired"):
            return "Your AWS session token has expired. Run `aws sso login --profile <name>` and retry."
        if code == "AccessDenied":
            return "Access denied by AWS. Confirm this profile has read access to the bucket."
        if code == "NoSuchBucket":
            return "That bucket does not exist (or is not visible with this profile/region)."
        return f"AWS error ({code}): {e}"
    # Some exceptions (e.g. streamlit.errors.NoSessionContext) carry no
    # message at all — str(e) is "". A blank error box tells the user
    # nothing happened to go wrong, which is worse than a generic one.
    return str(e) or f"Unexpected error: {type(e).__name__}"


def list_prefix(client, bucket: str, prefix: str) -> tuple[list[str], list[dict]]:
    """List immediate children of a prefix: (sub-prefixes, files)."""
    common_prefixes: list[str] = []
    files: list[dict] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        common_prefixes.extend(cp["Prefix"] for cp in page.get("CommonPrefixes", []))
        files.extend(page.get("Contents", []))
    return common_prefixes, files


def iter_objects_recursive(client, bucket: str, prefix: str):
    """Yield every object under a prefix (no delimiter), across all shards."""
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        yield from page.get("Contents", [])


def get_object_bytes(client, bucket: str, key: str) -> tuple[bytes, str]:
    resp = client.get_object(Bucket=bucket, Key=key)
    body = resp["Body"].read()
    etag = resp.get("ETag", "").strip('"')
    return body, etag
