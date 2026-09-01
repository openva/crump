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


#: What to publish, by file type: the include pattern and the Content-Type S3
#: should serve it with.
CONTENT_TYPES = {
    "*.json": "application/json",
    "*.csv": "text/csv",
}


def sync_command(
    source,
    bucket,
    prefix="",
    cache_seconds=86400,
    delete=False,
    dry_run=False,
    include="*.json",
):
    """Build the `aws s3 sync` command for publishing a directory.

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
        CONTENT_TYPES.get(include, "application/octet-stream"),
        # A static API is only useful if clients can read it cross-origin.
        "--cache-control",
        f"public, max-age={cache_seconds}",
        # Publish only the file type we generated; never sweep up stray local
        # files into a public bucket.
        "--exclude",
        "*",
        "--include",
        include,
    ]
    if delete:
        # Removes entities that no longer exist upstream. Off by default: a
        # partial run followed by --delete would erase most of the API.
        command.append("--delete")
    if dry_run:
        command.append("--dryrun")
    return command


#: How many lines of `aws s3 sync` output to keep. It prints one line per
#: object, and with two million objects capturing all of it costs hundreds of
#: megabytes -- enough to push a small server into the OOM killer. Only the
#: tail is ever shown, so only the tail is kept.
OUTPUT_TAIL_LINES = 20


def sync(source, bucket, prefix="", **kwargs):
    """Publish a directory to S3. Returns the tail of the CLI output.

    Streams rather than buffering: `aws s3 sync` emits a line per object, and
    capturing two million of them would cost more memory than the rest of
    Crump put together.
    """
    if not aws_available():
        raise PublishError("the AWS CLI is not installed; install it or sync manually")
    command = sync_command(source, bucket, prefix, **kwargs)
    return _run_streaming(command, "aws s3 sync")


def _run_streaming(command, label):
    """Run a command, keeping only the tail of its output.

    Returns the last OUTPUT_TAIL_LINES lines, and the total line count, as a
    single string. Raises PublishError on a non-zero exit.
    """
    from collections import deque

    tail = deque(maxlen=OUTPUT_TAIL_LINES)
    lines = 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    for line in process.stdout:
        stripped = line.rstrip()
        if stripped:
            tail.append(stripped)
            lines += 1
    process.wait()

    if process.returncode != 0:
        raise PublishError(
            f"{label} failed ({process.returncode}): " + " / ".join(list(tail)[-3:])
        )

    return "\n".join(tail)


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
    return _run_streaming(command, "aws s3 cp")
