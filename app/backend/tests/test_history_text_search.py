"""GET /api/history/text-search (NS-29): find videos by words inside their stored texts."""
from datetime import datetime, timedelta

import pytest_asyncio
from sqlalchemy import text

from services.text_search import find_hits, make_snippet

WORD = "зиррокс"  # a word that exists nowhere else in the test data


@pytest_asyncio.fixture
async def make_video(db_session):
    """Factory: add a video with one formatted-text row; everything is removed afterwards."""
    from models.models import SubtitleFormatted, Video
    created: list[str] = []
    counter = {"n": 0}

    async def make(video_id, title="T", author="A", url=None, age_days=0, **texts):
        counter["n"] += 1
        v = Video(url=url or f"https://www.youtube.com/watch?v={video_id}", video_id=video_id, title=title,
                  author=author, duration=60, created_at=datetime.utcnow() - timedelta(days=age_days))
        db_session.add(v)
        await db_session.flush()
        db_session.add(SubtitleFormatted(video_id=v.id, language="ru", text_length=10, processing_status="success",
                                         formatted_text=texts.get("formatted_text", "пусто"),
                                         cleaned_text=texts.get("cleaned_text"),
                                         summary_text=texts.get("summary_text"),
                                         mindmap_text=texts.get("mindmap_text")))
        await db_session.commit()
        created.append(v.id)
        return v

    yield make
    for vid in created:
        await db_session.execute(text("DELETE FROM subtitles_formatted WHERE video_id = :v"), {"v": vid})
        await db_session.execute(text("DELETE FROM videos WHERE id = :v"), {"v": vid})
    await db_session.commit()


# --- the matching helpers -------------------------------------------------------

def test_find_hits_is_case_insensitive_for_cyrillic_and_counts_every_match():
    assert find_hits("Привет, ПРИВЕТ и привет", "привет") == (3, 0)
    assert find_hits("ничего", "привет") == (0, None)


def test_find_hits_keeps_positions_when_lowercasing_changes_the_length():
    # 'İ' lower-cases to two characters; the position must still index the original text
    assert find_hits("İİ слово", "слово") == (1, 3)


def test_snippet_is_a_window_on_one_line_with_ellipses():
    t = "a" * 200 + "\n\nНАЙДЕНО слово\n" + "b" * 200
    s = make_snippet(t, 202, len("слово"))
    assert s.startswith("…") and s.endswith("…") and "\n" not in s and "НАЙДЕНО" in s
    assert make_snippet("коротко", 2, 3) == "коротко"


# --- the endpoint -----------------------------------------------------------------

async def test_finds_a_cyrillic_word_in_any_case_and_reports_part_position_and_snippet(client, make_video):
    body = "Начало текста. Тут ЗиррОкс встречается, потом ещё Зирркос нет. Конец."
    await make_video("srchCyr0001", title="Кириллица", formatted_text=body)
    r = await client.get("/api/history/text-search", params={"q": WORD.upper()})
    assert r.status_code == 200
    hit = next(v for v in r.json()["videos"] if v["video_id"] == "srchCyr0001")
    assert hit["title"] == "Кириллица" and hit["counts"] == {"transcript": 1}
    m = hit["matches"][0]
    assert m["part"] == "transcript" and m["position"] == body.lower().index(WORD)
    assert "ЗиррОкс" in m["snippet"]


async def test_reports_the_hit_count_and_first_match_of_each_part(client, make_video):
    await make_video("srchParts001", formatted_text=f"{WORD} раз. {WORD} два.", cleaned_text=f"чисто {WORD}",
                     summary_text="без слова", mindmap_text=f"# {WORD}")
    hit = next(v for v in (await client.get("/api/history/text-search", params={"q": WORD})).json()["videos"]
               if v["video_id"] == "srchParts001")
    assert hit["counts"] == {"cleaned": 1, "transcript": 2, "mindmap": 1}  # summary has no hit
    assert {m["part"]: m["position"] for m in hit["matches"]} == {"cleaned": 6, "transcript": 0, "mindmap": 2}


async def test_searches_the_whole_history_not_just_the_first_page(client, make_video):
    await make_video("srchOldest01", formatted_text=f"давно про {WORD}", age_days=400)
    for i in range(25):  # more than one history page (20) of newer videos without the word
        await make_video(f"srchNoise{i:03d}", age_days=i)
    r = await client.get("/api/history/text-search", params={"q": WORD})
    assert [v["video_id"] for v in r.json()["videos"]] == ["srchOldest01"]
    assert r.json()["searched"] >= 26


async def test_newest_first_and_limit_stops_the_search(client, make_video):
    for i in range(4):
        await make_video(f"srchOrder{i:02d}", formatted_text=f"{WORD} {i}", age_days=i)
    ids = [v["video_id"] for v in (await client.get("/api/history/text-search",
                                                    params={"q": WORD, "limit": 2})).json()["videos"]]
    assert ids == ["srchOrder00", "srchOrder01"]


async def test_short_or_missing_query_is_400_and_no_match_is_an_empty_list(client, make_video):
    assert (await client.get("/api/history/text-search")).status_code == 400
    assert (await client.get("/api/history/text-search", params={"q": " ab "})).status_code == 400
    r = await client.get("/api/history/text-search", params={"q": "qqqqnomatchqqqq"})
    assert r.status_code == 200 and r.json()["videos"] == []


async def test_pending_placeholders_are_not_searched(client, make_video):
    await make_video("srchPend0001", url="__pending__srchPend0001", formatted_text=f"{WORD}")
    r = await client.get("/api/history/text-search", params={"q": WORD})
    assert all(v["video_id"] != "srchPend0001" for v in r.json()["videos"])


async def test_the_query_is_data_not_sql_or_a_path(client, make_video):
    for q in ("'; DROP TABLE videos; --", "../../etc/passwd", "%%%", "___"):
        r = await client.get("/api/history/text-search", params={"q": q})
        assert r.status_code == 200 and r.json()["videos"] == []
    assert (await client.get("/api/history")).status_code == 200
