"""Publishing atomized output to S3 as a static API.

This shells out to the AWS CLI rather than using boto3: `aws s3 sync` already
handles parallelism, retries, and skipping unchanged objects, and syncing two
million small files is exactly what it is good at. Adding boto3 would mean
reimplementing that badly.
"""

import os
import shutil
import subprocess


class PublishError(Exception):
    """Publishing to S3 failed."""


def aws_available():
    """Whether the AWS CLI is on PATH."""
    return shutil.which("aws") is not None


def sync_command(
    source, bucket, prefix="", cache_seconds=86400, delete=False, dry_run=False
):
    """Build the `aws s3 sync` command for publishing entity JSON.

    Returns the argument list rather than running it, so callers can show the
    user exactly what would happen.
    """
    destination = f"s3://{bucket}"
    if prefix:
        destination += "/" + prefix.strip("/")

    command = [
        "aws",
        "s3",
        "sync",
        source,
        destination,
        "--content-type",
        "application/json",
        # A static API is only useful if clients can read it cross-origin.
        "--cache-control",
        f"public, max-age={cache_seconds}",
        # Only .json files; never publish stray local files.
        "--exclude",
        "*",
        "--include",
        "*.json",
    ]
    if delete:
        # Removes entities that no longer exist upstream. Off by default: a
        # partial run followed by --delete would erase most of the API.
        command.append("--delete")
    if dry_run:
        command.append("--dryrun")
    return command


def sync(source, bucket, prefix="", **kwargs):
    """Publish a directory of entity JSON to S3. Returns the CLI output."""
    if not aws_available():
        raise PublishError("the AWS CLI is not installed; install it or sync manually")
    command = sync_command(source, bucket, prefix, **kwargs)
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        raise PublishError(
            f"aws s3 sync failed ({error.returncode}): {error.stderr.strip()}"
        ) from error
    return result.stdout


def upload_command(path, bucket, key, content_type=None, dry_run=False):
    """Build the `aws s3 cp` command for uploading a single file.

    Used for the SQLite database, which is one large object rather than the
    millions of small ones `sync_command` handles.
    """
    command = [
        "aws",
        "s3",
        "cp",
        path,
        f"s3://{bucket}/{key.lstrip('/')}",
    ]
    if content_type:
        command += ["--content-type", content_type]
    if dry_run:
        command.append("--dryrun")
    return command


def upload_file(path, bucket, key, content_type=None, dry_run=False):
    """Upload one file to S3. Returns the CLI output."""
    if not os.path.isfile(path):
        raise PublishError(f"no such file: {path}")
    if not aws_available():
        raise PublishError(
            "the AWS CLI is not installed; install it or upload manually"
        )
    command = upload_command(
        path, bucket, key, content_type=content_type, dry_run=dry_run
    )
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        raise PublishError(
            f"aws s3 cp failed ({error.returncode}): {error.stderr.strip()}"
        ) from error
    return result.stdout
