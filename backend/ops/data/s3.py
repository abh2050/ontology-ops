"""Fetch exactly the five permitted source files from S3 into a private temp directory."""

from __future__ import annotations

import tempfile
from pathlib import Path
from urllib.parse import urlparse

from ops.data.sources import SOURCES


def download_sources(uri: str) -> Path:
    import boto3

    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError("expected s3://bucket/prefix")
    prefix = parsed.path.strip("/")
    target = Path(tempfile.mkdtemp(prefix="ops-import-"))
    s3 = boto3.client("s3")
    for filename, _ in SOURCES.values():
        key = f"{prefix}/{filename}" if prefix else filename
        s3.download_file(parsed.netloc, key, str(target / filename))
    return target
