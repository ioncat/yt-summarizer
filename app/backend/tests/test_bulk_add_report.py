"""NS-24: POST /api/queue/bulk takes any number of links, keeps their order, and gives every skipped link an explicit reason."""
import pytest

from tests.baseline_helpers import VIDEO_ID, reset_queue

URL = "https://www.youtube.com/watch?v={}"


@pytest.fixture(autouse=True)
async def _empty_queue(client):
    await reset_queue()
    yield
    await reset_queue()


def vid(n: int) -> str:
    return f"bulk{n:07d}"                 # 11 characters, like a YouTube id


async def test_fifty_distinct_links_give_fifty_rows_in_the_order_they_were_sent(client):
    links = [URL.format(vid(n)) for n in range(50)]
    r = await client.post("/api/queue/bulk", json={"urls": links, "pipeline_stages": ["extract"]})
    body = r.json()
    assert r.status_code == 200 and body["added"] == 50 and len(body["ids"]) == 50
    assert body["invalid"] == [] and body["duplicates"] == [] and body["duplicate_details"] == []
    items = (await client.get("/api/queue")).json()["items"]
    assert len(items) == 50
    assert [i["url"] for i in items] == links                          # the queue lists them as sent
    assert [i["id"] for i in items] == body["ids"]                     # and the ids come back in the same order
    assert [i["video_id"] for i in items] == [vid(n) for n in range(50)]


async def test_every_skipped_link_has_its_own_reason(client, seeded_video):
    queued = URL.format("queued00001")
    assert (await client.post("/api/queue/bulk", json={"urls": [queued]})).json()["added"] == 1
    new = URL.format("brandnew0001")
    processed = URL.format(VIDEO_ID)
    twice = f"https://youtu.be/{vid(1)}"
    links = [new, processed, queued, URL.format(vid(1)), twice, "https://example.com/watch?v=abcdefghijk", "not a link"]
    body = (await client.post("/api/queue/bulk", json={"urls": links, "pipeline_stages": ["extract"]})).json()
    assert body["added"] == 2                                          # brandnew0001 and the first bulk0000001
    reasons = {d["url"]: (d["video_id"], d["reason"]) for d in body["duplicate_details"]}
    assert reasons == {
        processed: (VIDEO_ID, "processed"),
        queued: ("queued00001", "in_queue"),
        twice: (vid(1), "in_list"),                                    # the same video, earlier in this very list
    }
    assert sorted(body["duplicates"]) == sorted(reasons)
    assert body["invalid"] == ["https://example.com/watch?v=abcdefghijk", "not a link"]       # not YouTube links, and only these


async def test_a_duplicate_in_the_list_is_not_invalid_and_the_first_copy_is_the_one_queued(client):
    a, b = URL.format(vid(1)), URL.format(vid(2))
    body = (await client.post("/api/queue/bulk", json={"urls": [a, b, a, b, a]})).json()
    assert body["added"] == 2 and body["invalid"] == []
    assert body["duplicates"] == [a, b, a]                             # in the order the repeats appear in the list
    assert [d["reason"] for d in body["duplicate_details"]] == ["in_list"] * 3
    assert [i["url"] for i in (await client.get("/api/queue")).json()["items"]] == [a, b]


async def test_the_report_has_one_entry_per_link_in_the_order_sent(client, seeded_video):
    queued = URL.format("queued00001")
    await client.post("/api/queue/bulk", json={"urls": [queued]})
    a = URL.format(vid(1))
    links = [a, URL.format(VIDEO_ID), "nonsense", a, queued, URL.format(vid(2)), f"https://youtu.be/{vid(2)}"]
    body = (await client.post("/api/queue/bulk", json={"urls": links, "pipeline_stages": ["extract"]})).json()
    assert [(e["url"], e["status"]) for e in body["report"]] == [
        (a, "added"), (URL.format(VIDEO_ID), "processed"), ("nonsense", "invalid"), (a, "in_list"), (queued, "in_queue"),
        (URL.format(vid(2)), "added"), (f"https://youtu.be/{vid(2)}", "in_list"),
    ]
    assert [e["video_id"] for e in body["report"]] == [vid(1), VIDEO_ID, None, vid(1), "queued00001", vid(2), vid(2)]
    assert sum(e["status"] == "added" for e in body["report"]) == body["added"] == 2


async def test_an_http_link_to_youtube_is_refused_with_its_own_reason(client):
    ok = URL.format(vid(1))
    http = f"http://www.youtube.com/watch?v={vid(2)}"
    other = "https://example.com/watch?v=abcdefghijk"
    body = (await client.post("/api/queue/bulk", json={"urls": [ok, http, other, "http://youtu.be/" + vid(3)]})).json()
    assert body["added"] == 1 and body["invalid"] == [http, other, "http://youtu.be/" + vid(3)]    # still refused
    assert [(e["status"], e.get("reason")) for e in body["report"]] == [
        ("added", None), ("invalid", "http_only"), ("invalid", "not_youtube"), ("invalid", "http_only")]
    assert [i["video_id"] for i in (await client.get("/api/queue")).json()["items"]] == [vid(1)]    # nothing was queued for http
