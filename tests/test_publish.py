"""Tests for S3 publishing.

Only the command construction is tested -- these must never touch a real
bucket.
"""

import pytest

from crumplib import publish


class TestSyncCommand:
    def test_builds_a_sync_to_the_bucket_root(self):
        command = publish.sync_command("out/entity", "data.vabusinesses.org")
        assert command[:5] == [
            "aws",
            "s3",
            "sync",
            "out/entity",
            "s3://data.vabusinesses.org",
        ]

    def test_prefix_becomes_a_key_path(self):
        command = publish.sync_command(
            "out/entity", "data.vabusinesses.org", prefix="entity"
        )
        assert "s3://data.vabusinesses.org/entity" in command

    def test_strips_slashes_from_prefix(self):
        command = publish.sync_command("out", "bucket", prefix="/entity/")
        assert "s3://bucket/entity" in command

    def test_sets_json_content_type(self):
        command = publish.sync_command("out", "bucket")
        assert command[command.index("--content-type") + 1] == "application/json"

    def test_sets_cache_control(self):
        command = publish.sync_command("out", "bucket", cache_seconds=3600)
        assert "public, max-age=3600" in command

    def test_only_uploads_json(self):
        """Never publish stray local files into a public bucket."""
        command = publish.sync_command("out", "bucket")
        assert command[command.index("--exclude") + 1] == "*"
        assert command[command.index("--include") + 1] == "*.json"

    def test_delete_is_off_by_default(self):
        """A partial run plus --delete would erase most of the API."""
        assert "--delete" not in publish.sync_command("out", "bucket")

    def test_delete_when_requested(self):
        assert "--delete" in publish.sync_command("out", "bucket", delete=True)

    def test_dry_run(self):
        assert "--dryrun" in publish.sync_command("out", "bucket", dry_run=True)


class TestSync:
    def test_raises_without_the_aws_cli(self, monkeypatch):
        monkeypatch.setattr(publish, "aws_available", lambda: False)
        with pytest.raises(publish.PublishError, match="AWS CLI"):
            publish.sync("out", "bucket")


class TestUploadCommand:
    def test_builds_a_cp_command(self):
        command = publish.upload_command(
            "crump.db", "data.vabusinesses.org", "crump.db"
        )
        assert command == [
            "aws",
            "s3",
            "cp",
            "crump.db",
            "s3://data.vabusinesses.org/crump.db",
        ]

    def test_strips_leading_slash_from_key(self):
        command = publish.upload_command("crump.db", "bucket", "/db/crump.db")
        assert "s3://bucket/db/crump.db" in command

    def test_sets_content_type_when_given(self):
        command = publish.upload_command(
            "x.db", "b", "x.db", content_type="application/vnd.sqlite3"
        )
        assert command[command.index("--content-type") + 1] == (
            "application/vnd.sqlite3"
        )

    def test_dry_run(self):
        assert "--dryrun" in publish.upload_command("x.db", "b", "x.db", dry_run=True)


class TestUploadFile:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(publish.PublishError, match="no such file"):
            publish.upload_file(str(tmp_path / "nope.db"), "bucket", "k")

    def test_raises_without_the_aws_cli(self, tmp_path, monkeypatch):
        path = tmp_path / "x.db"
        path.write_bytes(b"")
        monkeypatch.setattr(publish, "aws_available", lambda: False)
        with pytest.raises(publish.PublishError, match="AWS CLI"):
            publish.upload_file(str(path), "bucket", "k")
