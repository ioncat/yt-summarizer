"""Rule 19 for uploaded files: no test may write into (or read from) the live app/data/uploads. conftest.py points every upload-folder
function at a temp folder for the whole run and has a session guard that fails the run if the live folder changed."""
import os

import pytest

from tests import conftest as ct


def test_every_upload_folder_function_points_at_the_temp_folder_not_the_live_one():
    import routers.process as proc
    import routers.result_stages as result
    import routers.settings as settings
    import services.file_stt as fs
    live = os.path.normcase(ct.LIVE_UPLOADS)
    for name, fn in (("file_stt.uploads_dir", fs.uploads_dir), ("process.uploads_dir", proc.uploads_dir),
                     ("settings._uploads_dir", settings._uploads_dir), ("result_stages._uploads_dir", result._uploads_dir)):
        got = os.path.normcase(os.path.abspath(fn()))
        assert got != live and got == os.path.normcase(os.path.abspath(ct.TEST_UPLOADS)), name
    assert os.path.normcase(os.path.abspath(ct.LIVE_UPLOADS)).endswith(os.path.normcase(os.path.join("app", "data", "uploads")))


async def test_an_upload_made_without_any_special_fixture_lands_in_the_temp_folder(client):
    """The case that leaked: a test that posts a file and forgets to redirect the folder."""
    before_live = ct._snapshot_uploads(ct.LIVE_UPLOADS)
    r = await client.post("/api/process/file", files={"file": ("guard.m4a", b"fakeaudio", "audio/mp4")}, data={"language": "auto"})
    assert r.status_code == 200
    saved = [f for f in os.listdir(ct.TEST_UPLOADS) if f.endswith(".m4a")]
    assert saved, "the upload was not saved in the temp folder"
    assert ct._snapshot_uploads(ct.LIVE_UPLOADS) == before_live              # and nothing in the live one
    # tidy: remove the queue item, the task and the saved file
    from sqlalchemy import text
    from models.database import AsyncSessionLocal
    video_id = r.json()["video_id"]
    await client.delete(f"/api/process/file/{video_id}")
    async with AsyncSessionLocal() as db:
        for t in ("processing_tasks",):
            await db.execute(text(f"DELETE FROM {t} WHERE video_id IN (SELECT id FROM videos WHERE video_id=:v)"), {"v": video_id})
        await db.execute(text("DELETE FROM videos WHERE video_id=:v"), {"v": video_id})
        await db.execute(text("DELETE FROM processing_stages WHERE video_id = :v"), {"v": video_id})
        await db.commit()
    for f in saved:
        os.remove(os.path.join(ct.TEST_UPLOADS, f))


def test_the_snapshot_sees_added_removed_and_changed_files(tmp_path):
    """The guard compares snapshots of the live folder; this proves the comparison on a folder of its own."""
    (tmp_path / "keep.m4a").write_bytes(b"1234")
    (tmp_path / "gone.m4a").write_bytes(b"1")
    (tmp_path / "grow.m4a").write_bytes(b"1")
    before = ct._snapshot_uploads(str(tmp_path))
    assert ct._snapshot_uploads(str(tmp_path)) == before                       # nothing happened: equal
    (tmp_path / "gone.m4a").unlink()
    (tmp_path / "grow.m4a").write_bytes(b"12345")
    (tmp_path / "new.m4a").write_bytes(b"9")
    after = ct._snapshot_uploads(str(tmp_path))
    assert after != before
    assert ct.describe_uploads_change(before, after) == "added ['new.m4a'], removed ['gone.m4a'], changed ['grow.m4a']"
    assert ct._snapshot_uploads(str(tmp_path / "does-not-exist")) == []
